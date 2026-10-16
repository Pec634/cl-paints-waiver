package com.clpaints.client;

import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Environment;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends ComponentActivity {
    private WebView web;
    private ProgressBar progress;
    private LinearLayout errorPanel;
    private TextView errorText;
    private ValueCallback<Uri[]> fileCallback;
    private String retryUrl = PortalPolicy.HOME;
    private boolean failed;
    private static final int PICK_FILE = 100;
    private static final int PINK = Color.rgb(197, 29, 104);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(255, 249, 245));
        if (android.os.Build.VERSION.SDK_INT >= 30) {
          root.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
          });
        } else {
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
                return insets;
            });
        }
        setContentView(root);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() {
                if (errorPanel.getVisibility() == View.VISIBLE) load(PortalPolicy.HOME);
                else if (web.canGoBack()) web.goBack();
                else finish();
            }
        });

        LinearLayout header = new LinearLayout(this);
        header.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView brand = new TextView(this);
        brand.setText("CL Paints"); brand.setTextColor(PINK); brand.setTextSize(22);
        brand.setPadding(dp(16), dp(12), dp(8), dp(12));
        header.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));
        Button refresh = button("Refresh", v -> load(currentUrl()));
        header.addView(refresh);
        Button more = button("More", this::showMenu);
        header.addView(more);
        root.addView(header);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        root.addView(progress, new LinearLayout.LayoutParams(-1, dp(3)));

        errorPanel = new LinearLayout(this);
        errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setPadding(dp(24), dp(32), dp(24), dp(32));
        errorText = new TextView(this); errorText.setTextSize(18);
        errorPanel.addView(errorText);
        errorPanel.addView(button("Try again", v -> load(retryUrl)));
        errorPanel.addView(button("Email CL Paints", v -> external("mailto:info@clpaints.com")));
        root.addView(errorPanel, new LinearLayout.LayoutParams(-1, 0, 1));
        errorPanel.setVisibility(View.GONE);

        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setGeolocationEnabled(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setUserAgentString(settings.getUserAgentString() + " CLPaintsAndroid/0.1");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                String url = req.getUrl().toString();
                // Embedded HTTPS verification/payment frames are not top-level navigation.
                if (!req.isForMainFrame()) return !"https".equalsIgnoreCase(req.getUrl().getScheme());
                if (PortalPolicy.trusted(url)) return false;
                if (req.isForMainFrame() && req.hasGesture()) external(url);
                else if (req.isForMainFrame()) {
                    // Redirects to a payment provider should open outside the signed-in WebView.
                    if (PortalPolicy.external(url)) external(url);
                }
                return true;
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                failed = false;
                progress.setVisibility(View.VISIBLE);
                if (PortalPolicy.trusted(url)) retryUrl = url;
            }
            @Override public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
                CookieManager.getInstance().flush();
                if (!failed) { web.setVisibility(View.VISIBLE); errorPanel.setVisibility(View.GONE); }
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError error) {
                if (req.isForMainFrame()) showError("We couldn't connect. Check your internet connection, then try again.");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest req, WebResourceResponse response) {
                if (req.isForMainFrame() && response.getStatusCode() >= 500)
                    showError("The client portal is temporarily unavailable. Please try again shortly.");
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                showError("A secure connection couldn't be established. Please try again later.");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int value) { progress.setProgress(value); }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                if (!PortalPolicy.trusted(view.getUrl())) { callback.onReceiveValue(null); return true; }
                fileCallback = callback;
                Intent intent = params.createIntent();
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                try { startActivityForResult(intent, PICK_FILE); }
                catch (ActivityNotFoundException error) {
                    fileCallback.onReceiveValue(null); fileCallback = null;
                    toast("No file picker is available on this phone.");
                }
                return true;
            }
        });
        web.setDownloadListener((url, userAgent, disposition, mimeType, length) -> download(url, userAgent, disposition, mimeType));

        LinearLayout tabs = new LinearLayout(this);
        for (String[] tab : new String[][]{{"Home", ""}, {"Bookings", "bookings"}, {"Waivers", "waivers"}, {"Rewards", "rewards"}}) {
            Button item = button(tab[0], v -> load(PortalPolicy.HOME + tab[1]));
            item.setTextSize(12); item.setMinWidth(0); item.setMinimumWidth(0);
            tabs.addView(item, new LinearLayout.LayoutParams(0, dp(56), 1));
        }
        root.addView(tabs);
        // Restore cookies through WebView's cookie store, not through saved credentials.
        if (state == null || web.restoreState(state) == null) load(PortalPolicy.HOME);
    }

    private void showMenu(View anchor) {
        PopupMenu menu = new PopupMenu(this, anchor);
        menu.getMenu().add("Contact / messages").setOnMenuItemClickListener(item -> { load(PortalPolicy.HOME + "contact"); return true; });
        menu.getMenu().add("Account").setOnMenuItemClickListener(item -> { load(PortalPolicy.HOME + "account"); return true; });
        menu.getMenu().add("Open in browser").setOnMenuItemClickListener(item -> { external(currentUrl()); return true; });
        menu.show();
    }
    private void download(String url, String agent, String disposition, String mime) {
        if (!PortalPolicy.trusted(url)) { toast("Open this document in your browser to download it."); return; }
        String name = URLUtil.guessFileName(url, disposition, mime).replaceAll("[^a-zA-Z0-9._-]", "_");
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
        String cookies = CookieManager.getInstance().getCookie(url);
        if (cookies != null) request.addRequestHeader("Cookie", cookies);
        request.addRequestHeader("User-Agent", agent);
        if (mime != null) request.setMimeType(mime);
        request.setTitle(name);
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        // App-owned storage avoids asking for broad access to the client's files.
        request.setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, System.currentTimeMillis() + "-" + name);
        try {
            ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(request);
            toast("Downloading. Open the download notification when it finishes.");
        } catch (RuntimeException error) { toast("This download couldn't be started. Please try again."); }
    }
    private void external(String url) {
        if (!PortalPolicy.external(url)) { toast("This link isn't supported in the app."); return; }
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (ActivityNotFoundException error) { toast("No app is available to open this link."); }
    }
    private void load(String url) {
        if (!PortalPolicy.trusted(url)) return;
        failed = false; errorPanel.setVisibility(View.GONE); web.setVisibility(View.VISIBLE);
        web.loadUrl(url);
    }
    private String currentUrl() { return PortalPolicy.trusted(web.getUrl()) ? web.getUrl() : PortalPolicy.HOME; }
    private void showError(String message) {
        failed = true; progress.setVisibility(View.GONE); web.setVisibility(View.GONE);
        errorText.setText(message); errorPanel.setVisibility(View.VISIBLE);
    }
    private Button button(String title, View.OnClickListener action) {
        Button result = new Button(this); result.setText(title); result.setTextColor(PINK);
        result.setAllCaps(false); result.setOnClickListener(action); return result;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void toast(String message) { Toast.makeText(this, message, Toast.LENGTH_LONG).show(); }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_FILE && fileCallback != null) {
            Uri[] files = WebChromeClient.FileChooserParams.parseResult(result, data);
            if (files != null) {
                for (Uri file : files) {
                    if (file == null || !"content".equalsIgnoreCase(file.getScheme())) {
                        files = null;
                        toast("Please choose a file using your phone's file picker.");
                        break;
                    }
                }
            }
            fileCallback.onReceiveValue(files); fileCallback = null;
        }
    }
    @Override protected void onSaveInstanceState(Bundle state) { web.saveState(state); super.onSaveInstanceState(state); }
    @Override protected void onPause() { web.onPause(); CookieManager.getInstance().flush(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override protected void onDestroy() {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        web.destroy(); super.onDestroy();
    }
}
