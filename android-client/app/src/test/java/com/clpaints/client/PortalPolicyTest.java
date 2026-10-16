package com.clpaints.client;

import org.junit.Test;
import static org.junit.Assert.*;

public class PortalPolicyTest {
    @Test public void acceptsOnlyExactSecurePortalOrigins() {
        assertFalse(PortalPolicy.trusted(null));
        assertTrue(PortalPolicy.trusted(PortalPolicy.HOME));
        assertTrue(PortalPolicy.trusted("https://clpaints.com/client/bookings/4"));
        for (String url : new String[]{"http://my.clpaints.com/client/", "https://my.clpaints.com.evil.test/",
                "https://evil.test@my.clpaints.com/", "https://my.clpaints.com:8443/", "file:///etc/passwd",
                "javascript:alert(1)", "not a URL", "https://my.clpaints.com@evil.test/"}) {
            assertFalse(url, PortalPolicy.trusted(url));
        }
    }
    @Test public void blocksArbitraryExternalIntentSchemes() {
        assertFalse(PortalPolicy.external(null));
        assertTrue(PortalPolicy.external("https://checkout.example.com/"));
        assertTrue(PortalPolicy.external("mailto:info@clpaints.com"));
        assertFalse(PortalPolicy.external("intent://example/"));
        assertFalse(PortalPolicy.external("file:///private"));
        assertFalse(PortalPolicy.external("javascript:alert(1)"));
    }
}
