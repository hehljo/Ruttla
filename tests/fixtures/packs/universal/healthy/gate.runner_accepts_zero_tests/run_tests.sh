#!/bin/bash
out=$(pytest tests/)
if echo "$out" | grep -q 'no tests ran'; then
  echo 'nicht gemessen'; exit 2
fi
