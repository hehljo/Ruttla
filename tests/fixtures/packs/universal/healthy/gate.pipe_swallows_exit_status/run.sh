#!/bin/bash
out=$(python3 gate.py 2>&1)
status=$?
echo "$out" | head -3
