"""PCM -> MP3. lameenc is a ~0.4 MB wheel with LAME built in (no ffmpeg in the image).

MP3 (not Opus) because it plays everywhere incl. older iOS Safari, and libopus would need
48 kHz input while Piper voices are 22.05 kHz. 48 kbps CBR mono is transparent enough for
speech and ~7x smaller than the 16-bit WAV Piper produces.
"""
import lameenc

MP3_KBPS = 48


def encode_mp3(pcm16: bytes, sample_rate: int) -> bytes:
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(MP3_KBPS)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)  # 2 = high quality, still far faster than synthesis
    return bytes(encoder.encode(pcm16) + encoder.flush())
