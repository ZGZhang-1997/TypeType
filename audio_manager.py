import os
import re
import threading
import time

import edge_tts
import pyttsx3
import pygame


class AudioManager:
    def __init__(self, voice="en-US-AriaNeural"):
        self._voice = voice
        self._tmp_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "audio_cache"
        )
        os.makedirs(self._tmp_dir, exist_ok=True)
        pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
        self._channel = pygame.mixer.Channel(0)

        # Audio assets for current sentence
        self._word_sounds = {}  # word_lower -> pygame.mixer.Sound
        self._sentence_audio = None  # path to sentence mp3

        # Playback control
        self._lock = threading.Lock()
        self._current_word = None
        self._next_word = None
        self._play_sentence_flag = False
        self._stop_flag = False
        self._sentence_played_once = False
        self._word_play_counts = {}  # word_lower -> int

        self._thread = None

    # ── Audio generation ──────────────────────────────────────────

    def pregenerate_files(self, sentence, words):
        """Generate audio files only (no playback state changes).
        Safe to call while another sentence is playing.
        """
        seen = set()
        bare_words = []
        for w in words:
            bare = re.sub(r"[^a-zA-Z']", "", w).lower()
            if bare and bare not in seen:
                seen.add(bare)
                bare_words.append(bare)

        def _generate_words():
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
            for bare in bare_words:
                path = os.path.join(self._tmp_dir, f"word_{bare}.wav")
                if not os.path.exists(path):
                    engine.save_to_file(bare, path)
            engine.runAndWait()
            engine.stop()

        gen_thread = threading.Thread(target=_generate_words, daemon=True)
        gen_thread.start()

        sentence_path = os.path.join(
            self._tmp_dir, f"sent_{hash(sentence) & 0xFFFFFFFF:08x}.mp3"
        )
        if not os.path.exists(sentence_path):
            comm = edge_tts.Communicate(sentence, self._voice)
            comm.save_sync(sentence_path)

        gen_thread.join()

    def prepare_sentence(self, sentence, words):
        """Pre-generate all audio for a sentence and load into playback state.
        `words` is the list of display-words (may include punctuation).
        Called from a background thread by the app.
        """
        self.stop()

        self._word_sounds.clear()
        self._sentence_audio = None
        self._word_play_counts.clear()

        # Generate files (skips if already exist from prefetch)
        self.pregenerate_files(sentence, words)

        # Collect bare words
        seen = set()
        bare_words = []
        for w in words:
            bare = re.sub(r"[^a-zA-Z']", "", w).lower()
            if bare and bare not in seen:
                seen.add(bare)
                bare_words.append(bare)

        # Load word sounds into pygame
        for bare in bare_words:
            path = os.path.join(self._tmp_dir, f"word_{bare}.wav")
            if os.path.exists(path) and os.path.getsize(path) > 0:
                try:
                    self._word_sounds[bare] = pygame.mixer.Sound(path)
                except Exception:
                    pass

        sentence_path = os.path.join(
            self._tmp_dir, f"sent_{hash(sentence) & 0xFFFFFFFF:08x}.mp3"
        )
        if os.path.exists(sentence_path):
            self._sentence_audio = sentence_path

    # ── Playback control ──────────────────────────────────────────

    def play_word(self, word):
        bare = re.sub(r"[^a-zA-Z']", "", word).lower()
        with self._lock:
            self._current_word = bare
            self._next_word = None
            self._play_sentence_flag = False
            self._stop_flag = False
            self._sentence_played_once = False
            self._word_play_counts.setdefault(bare, 0)
        self._start_thread()

    def transition_to_word(self, word):
        bare = re.sub(r"[^a-zA-Z']", "", word).lower()
        with self._lock:
            if self._current_word == bare:
                return
            self._next_word = bare
            self._word_play_counts.setdefault(bare, 0)

    def play_sentence(self):
        with self._lock:
            self._play_sentence_flag = True
            self._next_word = None

    def stop(self):
        with self._lock:
            self._stop_flag = True
            self._current_word = None
            self._next_word = None
            self._play_sentence_flag = False
        self._channel.stop()
        pygame.mixer.music.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def has_sentence_played_once(self):
        with self._lock:
            return self._sentence_played_once

    # ── Internal playback thread ──────────────────────────────────

    def _start_thread(self):
        if self._thread and self._thread.is_alive():
            return  # already running, state change will steer it
        with self._lock:
            self._stop_flag = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        while True:
            with self._lock:
                if self._stop_flag:
                    return
                want_sentence = self._play_sentence_flag
                next_w = self._next_word
                cur_w = self._current_word

            if want_sentence:
                # Ensure current word finishes at least one play
                self._finish_current_word_play()
                self._play_sentence_loop()
                return

            if next_w and next_w != cur_w:
                # Finish current play, then switch
                self._finish_current_word_play()
                with self._lock:
                    if self._stop_flag:
                        return
                    self._current_word = next_w
                    self._next_word = None
                    cur_w = next_w

            # Play current word once
            sound = self._word_sounds.get(cur_w)
            if sound:
                self._channel.play(sound)
                while self._channel.get_busy():
                    with self._lock:
                        if self._stop_flag:
                            self._channel.stop()
                            return
                        if self._next_word or self._play_sentence_flag:
                            break
                    time.sleep(0.005)
                # If we finished naturally (not interrupted)
                if not self._channel.get_busy():
                    with self._lock:
                        self._word_play_counts[cur_w] = (
                            self._word_play_counts.get(cur_w, 0) + 1
                        )
            else:
                time.sleep(0.05)

    def _finish_current_word_play(self):
        """Ensure the current word has played at least once completely."""
        with self._lock:
            cur_w = self._current_word
            count = self._word_play_counts.get(cur_w, 0)
        if count > 0:
            # Already played at least once, wait for current play to finish
            while self._channel.get_busy():
                with self._lock:
                    if self._stop_flag:
                        return
                time.sleep(0.005)
            return

        # Must play at least once fully
        sound = self._word_sounds.get(cur_w)
        if not sound:
            return
        if not self._channel.get_busy():
            self._channel.play(sound)
        while self._channel.get_busy():
            with self._lock:
                if self._stop_flag:
                    return
            time.sleep(0.005)
        with self._lock:
            self._word_play_counts[cur_w] = self._word_play_counts.get(cur_w, 0) + 1

    def _play_sentence_loop(self):
        if not self._sentence_audio:
            with self._lock:
                self._sentence_played_once = True
            return

        pygame.mixer.music.load(self._sentence_audio)
        first_play_done = False

        while True:
            with self._lock:
                if self._stop_flag:
                    pygame.mixer.music.stop()
                    return

            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                with self._lock:
                    if self._stop_flag:
                        pygame.mixer.music.stop()
                        return
                time.sleep(0.01)

            if not first_play_done:
                first_play_done = True
                with self._lock:
                    self._sentence_played_once = True
            # Continue looping until stopped

    def cleanup(self):
        self.stop()
        pygame.mixer.quit()
