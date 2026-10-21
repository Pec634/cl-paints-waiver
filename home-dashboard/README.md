# Hearth — home overview

A separate, buildless home dashboard. It does not change or depend on the existing CL Paints app.

## Open locally

For a quick look, open `index.html` directly in your browser. A local HTTP server is recommended for consistent browser storage and camera access.

From this folder, run:

```powershell
..\.venv\Scripts\python.exe -m http.server 5173 --bind 127.0.0.1
```

Then visit http://127.0.0.1:5173. Alternatively use your installed Python with `python -m http.server 5173 --bind 127.0.0.1`.

No package installation or build is needed. Fonts load from Google Fonts, with system font fallbacks. Settings are stored in this browser's local storage, not shared across devices. Use the same address and port to keep accessing the same saved settings. No server, authentication or public deployment is included; use locally.

## Cameras

Choose **Add camera**, name your camera, and enter its camera web page or an existing viewer URL. The dashboard opens this viewer in a separate tab. An optional browser-compatible MP4/WebM video URL enables an inline player; this is not a direct Wansview Cloud integration. The dashboard does not fetch camera feeds until you use the player. It never reports cameras as live merely because a URL is saved.

Wansview models vary: some support a local web page or RTSP, while others require Wansview Cloud. Confirm the exact model before selecting an integration. RTSP cannot play directly in a browser; use an existing local bridge such as go2rtc to expose a compatible stream, or use your camera viewer link. This project does not install a bridge or discover cameras. HLS, MJPEG, WebRTC and proprietary Wansview Cloud streams are not supported by this simple video player. Camera viewer links can open external viewers supporting those formats.

URLs must use HTTP/HTTPS, without embedded credentials, query parameters or fragments. Use a viewer with its own login, rather than saving passwords or bearer tokens. HTTPS dashboards may block HTTP video; both the viewer and video must be reachable from the device using the dashboard. Do not port-forward cameras to the internet to make this work.

Official Wansview references:

- https://wansview.com/newsinfo/886352.html
- https://wansview.com/newsinfo/886330.html

## Your supplied camera inventory

- **GALAYOU G2-5MP indoor:** the manufacturer's dedicated G2 5MP page confirms RTSP/ONVIF through Wansview Cloud → Local Application. Enable local access there; browser playback still requires a local video bridge.
- **GALAYOU Y4 outdoor, two cameras:** check Local Application for RTSP/ONVIF. The manufacturer-supplied Y4/G2/G6/G7 manual documents local streaming for supported cameras. A local bridge is required for browser playback.
- **GALAYOU battery outdoor, two cameras:** the Amazon link could not be fetched, so the exact model remains unverified. GALAYOU's battery-camera FAQ states that battery models do not support RTSP/ONVIF. Plan on Wansview Cloud viewing rather than dashboard live video.

Sources: https://www.galayou-store.com/g25mp · https://www.galayou-store.com/y4 · https://www.galayou-store.com/r2_4p · https://m.media-amazon.com/images/I/B1wuSkVRgmL.pdf

The dashboard includes this compatibility guidance, without assuming camera locations or marking cameras connected. Pan/tilt, two-way audio and recordings are not implemented in the dashboard.

## Family calendar setup

In Google Calendar on desktop, select **Settings → Settings for my calendars → your family calendar → Integrate calendar**. Copy the **Calendar ID** into the dashboard's Settings.

This displays Google's own embedded agenda. Updates are managed by Google and appear when the embedded view refreshes; create/edit events with **Open Google Calendar**. No OAuth integration, calendar API access, event caching or two-way event editor is implemented here.

For a private family calendar, the viewing browser must be signed in to a Google account with calendar access, and Google must permit the embedded session. Browser restrictions on third-party cookies can prevent private calendars from appearing. If it fails, use the direct Google Calendar link. You do not need to make a family calendar public. This dashboard cannot inspect Google's cross-origin frame to verify that events loaded, so it says **configured**, rather than **connected**.

Google's guide: https://support.google.com/calendar/answer/41207

## Next integration step

For reliable private-calendar access without an embedded Google session, add a backend with Google OAuth and the Calendar API using your own Google Cloud project. Camera models, available local protocols, hosting choice, and Google OAuth credentials are needed before implementing full private integration. Never put OAuth client secrets or camera passwords into frontend files.
