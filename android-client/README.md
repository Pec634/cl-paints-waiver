# CL Paints Android client

An Android app for the existing HTTPS client portal. It uses the same accounts,
email-code verification, bookings, payments, waivers, QR codes, rewards and
messages as the website. This first version uses Android WebView for portal
screens, with native navigation, file picking, downloads and connection recovery.
It does not require a second database or changes to server authentication.

## Install a preview

After this project is pushed, open GitHub **Actions → Android preview APK**.
Select a successful run and download the **CL-Paints-Android-preview** artifact.
Unzip it and transfer `app-debug.apk` to your Android phone. Open it on the phone
and allow installation from that source when Android prompts. This is a testing
build, not a Play Store release. The preview has its own application ID,
`com.clpaints.client.preview`, separate from the eventual production app.

Android 8.0 or newer and an internet connection are required. Sign in using your
existing client email. Sessions follow the portal's expiry and remember-me rules;
the app does not store passwords or verification codes. Data entered into the
portal is real production data, so use a designated test client account.

## Build locally

Open this directory as an Android Studio project, using JDK 17 and Android SDK 36.
The included wrapper downloads the pinned Gradle 8.13 distribution. On Windows:

```text
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

On macOS/Linux use `bash gradlew testDebugUnitTest lintDebug assembleDebug`.
The APK is written to `app/build/outputs/apk/debug/app-debug.apk`. No `.env`,
server secrets or signing key belongs in this
project. Set the local SDK path in an ignored `local.properties` if needed.
If a preview update reports a signature conflict, uninstall the previous preview
first: local and ephemeral CI debug signing keys may differ. Production updates
will use a persistent signing identity.

## First device test

- Sign in with an email code; check expiry, remember-me and sign-out.
- Open bookings, payments, invoices, rewards and the account page.
- Complete a test waiver and verify the QR code is readable.
- Send a test client enquiry and a booking message.
- Upload an image through the system file picker.
- Download an invoice and open the completion notification.
- Try booking calendar downloads and confirm calendar import on the device.
- Open payment/email/external links; these open in the appropriate external app.
- Turn off connectivity, use retry, rotate the phone and test Android Back.
- Check text scaling, keyboard visibility and navigation on a small phone.

Only exact HTTPS portal hosts can stay inside the app. Other HTTPS links open in
the browser. Certificate errors are rejected, cleartext is disabled, backups are
disabled and there is no JavaScript-to-native bridge. Uploads use the system
picker without broad camera or photo-library permissions. Downloaded documents
use app-owned external storage and are removed when the app is uninstalled.

## Before Google Play publication

This is the first installable client version, not a completed store submission.
Complete device testing and resolve findings before inviting clients. Native
push notifications are not implemented: the portal's browser push integration
does not automatically work in Android WebView. External payment flows may need
the client to return to the app and refresh the booking afterwards. The app is
online-only; it does not promise offline access to QR codes or documents.

Prepare a Google Play developer account, store artwork/screenshots, privacy policy,
Data safety declaration and account-deletion flow/web link appropriate to the
portal's account creation. Review current Play requirements, including any
account-specific closed-testing requirements. Generate a production upload key,
retain it securely and use Android Studio **Generate Signed Bundle / APK → Android
App Bundle** to build the release. Never submit the preview debug APK to Play.
Choose the final application ID before the first store release; keep signing
material outside Git and outside chat. Store publication needs the account owner.

Useful references:
- https://developer.android.com/studio/publish
- https://support.google.com/googleplay/android-developer/answer/13327111
- https://support.google.com/googleplay/android-developer/answer/14151465
