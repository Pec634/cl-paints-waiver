package com.clpaints.pos;

import android.app.Application;
import com.sumup.reader.sdk.api.SumUpState;

public class PosApplication extends Application {
    @Override public void onCreate() {
        super.onCreate();
        SumUpState.init(this);
    }
}
