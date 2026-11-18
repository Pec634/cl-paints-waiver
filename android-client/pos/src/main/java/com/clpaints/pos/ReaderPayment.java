package com.clpaints.pos;

import java.math.BigDecimal;

/** Validate totals before opening any native payment UI. */
final class ReaderPayment {
    static boolean validAmount(String amount) {
        if (amount == null || !amount.matches("[0-9]{1,7}\\.[0-9]{2}")) return false;
        BigDecimal total = new BigDecimal(amount);
        return total.compareTo(new BigDecimal("1.00")) >= 0
            && total.compareTo(new BigDecimal("999999.99")) <= 0;
    }
}
