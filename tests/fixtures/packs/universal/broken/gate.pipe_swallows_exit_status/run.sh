#!/bin/bash
python3 gate.py 2>&1 | head -3
echo "EXIT: $?"
