package com.clpaints.pos;

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
import java.math.BigDecimal;
import com.sumup.merchant.reader.api.SumUpAPI;
import com.sumup.merchant.reader.api.SumUpLogin;
import com.sumup.merchant.reader.api.SumUpPayment;

public class MainActivity extends ComponentActivity {
    private WebView web;
    private ProgressBar progress;
    private LinearLayout errorPanel;
    private TextView errorText;
    private ValueCallback<Uri[]> fileCallback;
    private String retryUrl = PortalPolicy.HOME;
    private boolean failed;
    private Uri pendingPayment;
    private String pendingSale;
    private static final int PICK_FILE = 100;
    private static final int SUMUP_LOGIN = 201;
    private static final int SUMUP_CHECKOUT = 202;
    private static final int SUMUP_READER = 203;
    private static final int PINK = Color.rgb(197, 29, 104);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (state != null) {
            String payment = state.getString("pendingPayment");
            pendingPayment = payment == null ? null : Uri.parse(payment);
            pendingSale = state.getString("pendingSale");
        }
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
        brand.setText("CL Paints POS"); brand.setTextColor(PINK); brand.setTextSize(22);
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
        settings.setUserAgentString(settings.getUserAgentString() + " CLPaintsPOSAndroid/0.2 SumUpNative/1");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                String url = req.getUrl().toString();
                // Embedded HTTPS verification/payment frames are not top-level navigation.
                if (!req.isForMainFrame()) return !"https".equalsIgnoreCase(req.getUrl().getScheme());
                if ("sumupmerchant".equals(req.getUrl().getScheme())) {
                    if (req.hasGesture() && PortalPolicy.paymentPage(view.getUrl())) launchPayment(req.getUrl());
                    return true;
                }
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
        for (String[] tab : new String[][]{{"Till / waivers", "/admin/pos"}, {"Admin", "/admin"}}) {
            Button item = button(tab[0], v -> load("https://my.clpaints.com" + tab[1]));
            item.setTextSize(12); item.setMinWidth(0); item.setMinimumWidth(0);
            tabs.addView(item, new LinearLayout.LayoutParams(0, dp(56), 1));
        }
        root.addView(tabs);
        // Restore cookies through WebView's cookie store, not through saved credentials.
        if (state == null || web.restoreState(state) == null) load(PortalPolicy.HOME);
        handlePaymentReturn(getIntent());
    }

    private void showMenu(View anchor) {
        PopupMenu menu = new PopupMenu(this, anchor);
        menu.getMenu().add("Till / waiver search").setOnMenuItemClickListener(item -> { load(PortalPolicy.HOME); return true; });
        menu.getMenu().add("SumUp card reader").setOnMenuItemClickListener(item -> {
            if (SumUpAPI.isLoggedIn()) SumUpAPI.openCardReaderPage(this, SUMUP_READER);
            else toast("Start a card payment to sign in to SumUp and connect your reader.");
            return true;
        });
        menu.getMenu().add("Sign out of SumUp").setOnMenuItemClickListener(item -> {
            SumUpAPI.logout(); toast("Signed out of SumUp. Your staff sign-in is unchanged."); return true;
        });
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
    private void launchPayment(Uri uri) {
        String reference = uri.getQueryParameter("foreign-tx-id");
        if (!"pay".equals(uri.getHost()) || !"/1.0".equals(uri.getPath())
                || !"GBP".equals(uri.getQueryParameter("currency"))
                || !BuildConfig.APPLICATION_ID.equals(uri.getQueryParameter("app-id"))
                || !"clpaintspos://sumup-callback".equals(uri.getQueryParameter("callback"))
                || reference == null || !reference.matches("POS-[A-Za-z0-9_-]{20,50}")
                || !ReaderPayment.validAmount(uri.getQueryParameter("total"))
                || uri.getQueryParameter("affiliate-key") == null
                || uri.getQueryParameter("affiliate-key").trim().isEmpty()
                || uri.getQueryParameter("merchant-code") == null
                || uri.getQueryParameter("merchant-code").trim().isEmpty()) {
            toast("Payment setup does not match this POS app. Check the SumUp configuration."); return;
        }
        if (pendingPayment != null) { toast("A reader payment is already being prepared."); return; }
        android.content.SharedPreferences prefs = getSharedPreferences("payments", MODE_PRIVATE);
        if (prefs.getBoolean(reference, false)) {
            toast("This payment was already opened. Check its status with SumUp before taking another payment."); return;
        }
        pendingSale = web.getUrl().replaceFirst("/start$", "");
        pendingPayment = uri;
        if (!prefs.edit().putString("lastSale", pendingSale).commit()) {
            pendingPayment = null;
            toast("Could not save the payment reference. Try again."); return;
        }
        if (!SumUpAPI.isLoggedIn()) {
            SumUpAPI.openLoginActivity(this, SumUpLogin.builder(uri.getQueryParameter("affiliate-key")).build(), SUMUP_LOGIN);
        } else startReaderPayment();
    }
    private void startReaderPayment() {
        if (pendingPayment == null) return;
        Uri uri = pendingPayment;
        com.sumup.merchant.reader.models.Merchant merchant = SumUpAPI.getCurrentMerchant();
        if (merchant == null || !uri.getQueryParameter("merchant-code").equals(merchant.getMerchantCode())
                || merchant.getCurrency() != SumUpPayment.Currency.GBP) {
            pendingPayment = null;
            toast("Wrong SumUp merchant or currency. Use More > Sign out of SumUp, then activate the reader and sign in to the configured GBP merchant.");
            return;
        }
        String reference = uri.getQueryParameter("foreign-tx-id");
        android.content.SharedPreferences prefs = getSharedPreferences("payments", MODE_PRIVATE);
        if (prefs.getBoolean(reference, false)) {
            pendingPayment = null;
            toast("This payment was already opened. Check its status with SumUp."); return;
        }
        SumUpPayment payment = SumUpPayment.builder()
            .total(new BigDecimal(uri.getQueryParameter("total")))
            .currency(SumUpPayment.Currency.GBP)
            .title(uri.getQueryParameter("title"))
            .foreignTransactionId(reference)
            .configureRetryPolicy(2000, 60000, true)
            .build();
        // Persist the attempt before invoking checkout. An interruption must never auto-charge again.
        if (!prefs.edit().putBoolean(reference, true).commit()) {
            pendingPayment = null;
            toast("Could not save the payment attempt. No reader payment was started."); return;
        }
        pendingPayment = null;
        SumUpAPI.checkout(this, payment, SUMUP_CHECKOUT);
    }
    private void handlePaymentReturn(Intent intent) {
        Uri uri = intent == null ? null : intent.getData();
        if (uri != null && "clpaintspos".equals(uri.getScheme()) && "sumup-callback".equals(uri.getHost())) {
            // Callback fields are untrusted. Only the server can confirm payment.
            String sale = getSharedPreferences("payments", MODE_PRIVATE).getString("lastSale", PortalPolicy.HOME);
            load(sale); toast("Check the payment with SumUp to confirm the sale.");
        }
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent); setIntent(intent); handlePaymentReturn(intent);
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
        if (request == SUMUP_LOGIN) {
            if (data != null && data.getIntExtra(SumUpAPI.Response.RESULT_CODE, -1)
                    == SumUpAPI.Response.ResultCode.SUCCESSFUL && SumUpAPI.isLoggedIn()) startReaderPayment();
            else {
                pendingPayment = null;
                toast("SumUp sign-in was not completed. No reader payment was started. Tap Activate card reader to try sign-in again.");
            }
            return;
        }
        if (request == SUMUP_CHECKOUT) {
            pendingPayment = null;
            String sale = getSharedPreferences("payments", MODE_PRIVATE).getString("lastSale", PortalPolicy.HOME);
            load(sale);
            // SDK results are advisory. The authenticated server verifies the exact transaction.
            toast("Reader payment finished. Tap Check payment with SumUp to confirm the sale before taking another payment.");
            return;
        }
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
    @Override protected void onSaveInstanceState(Bundle state) {
        web.saveState(state);
        if (pendingPayment != null) state.putString("pendingPayment", pendingPayment.toString());
        state.putString("pendingSale", pendingSale);
        super.onSaveInstanceState(state);
    }
    @Override protected void onPause() { web.onPause(); CookieManager.getInstance().flush(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override protected void onDestroy() {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        web.destroy(); super.onDestroy();
    }
}
