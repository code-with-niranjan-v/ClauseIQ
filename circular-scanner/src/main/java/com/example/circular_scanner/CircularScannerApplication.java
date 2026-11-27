package com.example.circular_scanner;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class CircularScannerApplication {

	public static void main(String[] args) {
		SpringApplication.run(CircularScannerApplication.class, args);
	}

}
