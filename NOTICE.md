# Notices

PhantomPlay is an original client/host implementation inspired by the browser-remote-desktop
workflow popularized by noVNC. It does not vendor or copy the noVNC source tree.

Runtime binaries are downloaded by `scripts/bootstrap.py` from their official upstreams and
are not committed to this repository:

- FFmpeg builds: BtbN/FFmpeg-Builds (GPL build variants). FFmpeg is licensed under LGPL/GPL
  depending on build configuration; the downloaded `gpl` archives include GPL components.
  See https://ffmpeg.org/legal.html and the license files inside the downloaded archive.
- cloudflared: Cloudflare, Inc. See https://github.com/cloudflare/cloudflared/blob/master/LICENSE.
- vgamepad / ViGEmBus: Nefarius Software Solutions. ViGEmBus is archived; the driver installer
  is bundled by vgamepad on Windows. See https://github.com/nefarius/ViGEmBus and
  https://github.com/nefarius/ViGEmClient.
- Python dependencies retain their own licenses: aiohttp (Apache-2.0), mss (LGPL-3.0),
  Pillow (MIT-CMU), qrcode (BSD), python-xlib (LGPL-2.1), pyaudiowpatch (MIT),
  vgamepad (MIT).

If you redistribute a bundle that includes FFmpeg/cloudflared/driver installers, you must
comply with each upstream license and provide corresponding source/offers where required.
