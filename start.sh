#!/bin/bash
# Install system dependencies
apt-get update -qq && apt-get install -y -qq ffmpeg 2>/dev/null

# Install Python dependencies
pip install -q PyNaCl croniter 2>/dev/null

# Start the bot
exec python main.py
