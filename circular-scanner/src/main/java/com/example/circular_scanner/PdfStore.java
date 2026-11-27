package com.example.circular_scanner;

import io.minio.BucketExistsArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.errors.ErrorResponseException;
import java.io.ByteArrayInputStream;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
class PdfStore {
    private final MinioClient client;
    private final String bucket;
    private volatile boolean bucketReady;

    PdfStore(@Value("${scanner.minio.endpoint}") String endpoint,
             @Value("${scanner.minio.access-key}") String accessKey,
             @Value("${scanner.minio.secret-key}") String secretKey,
             @Value("${scanner.minio.bucket}") String bucket) {
        var builder = MinioClient.builder().endpoint(endpoint);
        if (!accessKey.isBlank() && !secretKey.isBlank()) {
            builder.credentials(accessKey, secretKey);
        }
        client = builder.build();
        client.setTimeout(10_000, 15_000, 30_000);
        this.bucket = bucket;
    }

    String bucket() {
        return bucket;
    }

    void put(String key, byte[] pdf) throws Exception {
        ensureBucket();
        client.putObject(PutObjectArgs.builder().bucket(bucket).object(key).contentType("application/pdf")
                .stream(new ByteArrayInputStream(pdf), pdf.length, -1).build());
    }

    private synchronized void ensureBucket() throws Exception {
        if (bucketReady) {
            return;
        }
        if (!client.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) {
            try {
                client.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
            } catch (ErrorResponseException e) {
                if (!"BucketAlreadyOwnedByYou".equals(e.errorResponse().code())) {
                    throw e;
                }
            }
        }
        bucketReady = true;
    }
}
