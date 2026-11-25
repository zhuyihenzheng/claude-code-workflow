package com.example.demo;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Configuration values are injected with @Value: allowed by guard and ArchUnit alike. */
@Component
public class AppInfo {

    @Value("${app.name:demo}")
    private String name;

    public String name() {
        return name;
    }
}
