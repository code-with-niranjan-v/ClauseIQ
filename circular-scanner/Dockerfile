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

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/circular-scanner-0.0.1-SNAPSHOT.jar /app/scanner.jar
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/scanner.jar"]
