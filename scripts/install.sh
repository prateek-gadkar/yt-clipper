#!/usr/bin/env bash
# yt-clipper Clip Watcher — one-time installer for Debian/Ubuntu.
# Everything installed here is free and open source. Total cost: $0.
set -euo pipefail

echo "==> System packages (ffmpeg, build tools, curl)"
sudo apt-get update
sudo apt-get install -y ffmpeg git curl cmake build-essential python3 python3-venv python3-pip

echo "==> Python venv + streamlink (the recorder)"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install streamlink

echo "==> whisper.cpp (local captions) — building from source"
WHISPER_DIR="${HOME}/whisper.cpp"
if [ ! -d "$WHISPER_DIR" ]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WHISPER_DIR"
fi
cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$WHISPER_DIR/build" --config Release -j"$(nproc)"
mkdir -p "$HOME/.local/bin"
ln -sf "$WHISPER_DIR/build/bin/whisper-cli" "$HOME/.local/bin/whisper-cli"
echo "    whisper-cli linked into ~/.local/bin (make sure it's on your PATH)"

echo "==> Whisper model (~1.5 GB, free)"
mkdir -p models
if [ ! -f models/ggml-medium.en.bin ]; then
  curl -L --fail -o models/ggml-medium.en.bin \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin
fi

echo
echo "Done. Next steps:"
echo "  1. cp config.example.toml config.toml && edit twitch.channel"
echo "  2. source .venv/bin/activate"
echo "  3. python -m clipper doctor     # everything should say OK"
echo "  4. python -m clipper watch      # leave it running — it waits for live by itself"
