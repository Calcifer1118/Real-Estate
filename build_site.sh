#!/bin/sh
# Wraps the demo page in a full HTML document so the proposal can show it in its phone frame (proposal/site/index.html).
set -e
cd "$(dirname "$0")"
mkdir -p proposal/site
{ printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body>\n'; cat demo/index.html; printf '</body></html>\n'; } > proposal/site/index.html
