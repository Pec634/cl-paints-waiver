package com.clpaints.pos;

import java.net.URI;
import java.util.Set;

/** Keep authenticated pages on our exact HTTPS origins. */
final class PortalPolicy {
    static final String HOME = "https://my.clpaints.com/admin/pos";
    private static final Set<String> HOSTS = new java.util.HashSet<>(java.util.Arrays.asList(
        "my.clpaints.com", "clpaints.com", "www.clpaints.com"));

    static boolean trusted(String value) {
        if (value == null) return false;
        try {
            URI uri = URI.create(value);
            return "https".equalsIgnoreCase(uri.getScheme()) && uri.getUserInfo() == null
                && (uri.getPort() == -1 || uri.getPort() == 443)
                && uri.getHost() != null && HOSTS.contains(uri.getHost().toLowerCase(java.util.Locale.ROOT));
        } catch (IllegalArgumentException error) { return false; }
    }

    static boolean external(String value) {
        if (value == null) return false;
        try {
            String scheme = URI.create(value).getScheme();
            return "https".equalsIgnoreCase(scheme) || "mailto".equalsIgnoreCase(scheme)
                || "tel".equalsIgnoreCase(scheme) || "geo".equalsIgnoreCase(scheme);
        } catch (IllegalArgumentException error) { return false; }
    }

    static boolean paymentPage(String value) {
        if (!trusted(value)) return false;
        String path = URI.create(value).getPath();
        return path != null && path.matches("/admin/pos/sales/[0-9]+/start");
    }
}
