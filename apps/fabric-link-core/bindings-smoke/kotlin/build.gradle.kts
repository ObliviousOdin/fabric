plugins {
    kotlin("jvm") version "2.0.20"
    application
}

dependencies {
    implementation("net.java.dev.jna:jna:5.17.0")
}

kotlin {
    jvmToolchain(17)
}

sourceSets {
    main {
        kotlin.srcDir("../../target/generated-kotlin")
    }
}

application {
    mainClass.set("SmokeKt")
}

tasks.named<JavaExec>("run") {
    systemProperty(
        "jna.library.path",
        file("../../target/debug").absolutePath,
    )
}
