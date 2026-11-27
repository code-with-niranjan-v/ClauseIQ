# syntax=docker/dockerfile:1
FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN --mount=type=secret,id=maven_settings,target=/root/.m2/settings.xml \
    --mount=type=secret,id=java_truststore \
    --mount=type=cache,target=/root/.m2/repository \
    if [ -f /run/secrets/java_truststore ]; then \
      export MAVEN_OPTS="-Djavax.net.ssl.trustStore=/run/secrets/java_truststore"; \
    fi; \
    mvn --batch-mode --strict-checksums --no-transfer-progress -DskipTests package

FROM eclipse-temurin:21-jre AS java

FROM mcr.microsoft.com/playwright:v1.64.0-noble
WORKDIR /app
COPY --from=java /opt/java/openjdk /opt/java/openjdk
RUN npm install --omit=dev --no-audit --no-fund --no-save playwright@1.64.0
ENV PATH="/opt/java/openjdk/bin:${PATH}"
ENV SCANNER_BROWSER_FALLBACK=true
COPY download-pdf.cjs render-notification.cjs ./
COPY --from=build /build/target/circular-scanner-0.0.1-SNAPSHOT.jar /app/scanner.jar
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/scanner.jar"]
