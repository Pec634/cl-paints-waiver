package com.clpaints.pos;

import org.junit.Test;
import static org.junit.Assert.*;

public class ReaderPaymentTest {
    @Test public void requiresExactPositiveGbpTotalWithinTillLimit() {
        for (String amount : new String[]{"1.00", "7.50", "999999.99"})
            assertTrue(amount, ReaderPayment.validAmount(amount));
        for (String amount : new String[]{"0.00", "0.99", "-5.00", "7.501", "NaN", "1e2", "1000000.00", "7", " 7.50"})
            assertFalse(amount, ReaderPayment.validAmount(amount));
        assertFalse(ReaderPayment.validAmount(null));
    }
}
