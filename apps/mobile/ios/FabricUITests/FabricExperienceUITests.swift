import XCTest

final class FabricExperienceUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testScannerLedFirstRunHasOneClearPrimaryPath() {
        let app = launchFixture("onboarding")

        XCTAssertTrue(app.staticTexts["Connect your Fabric"].waitForExistence(timeout: 4))
        let scan = app.buttons["Scan pairing code"]
        let advanced = app.buttons["Advanced setup"]
        XCTAssertTrue(scan.exists)
        XCTAssertTrue(advanced.exists)
        XCTAssertFalse(app.staticTexts["Servers"].exists)

        scan.tap()
        XCTAssertTrue(
            app.navigationBars["Camera access"].waitForExistence(timeout: 4)
                || app.navigationBars["Scan pairing code"].waitForExistence(timeout: 1)
        )
        XCTAssertTrue(
            app.staticTexts["Allow camera access"].exists
                || app.staticTexts["Camera access is off"].exists
                || app.staticTexts["Camera is unavailable"].exists
                || app.staticTexts["Point your camera at the code shown by `fabric mobile`."].exists
        )
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.staticTexts["Connect your Fabric"].waitForExistence(timeout: 4))

        app.buttons["Advanced setup"].tap()
        XCTAssertTrue(app.navigationBars["Advanced setup"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.textFields["Fabric computer name"].exists)
        XCTAssertTrue(app.textFields["Fabric server address"].exists)
        XCTAssertTrue(app.buttons["Test address"].exists)
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.staticTexts["Connect your Fabric"].waitForExistence(timeout: 4))
    }

    func testReturningUserCanConnectOrScanAnotherCode() {
        let app = launchFixture("returning")

        XCTAssertTrue(app.staticTexts["Choose your Fabric"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.buttons["Scan another pairing code"].exists)
        XCTAssertTrue(app.staticTexts["Personal Mac"].exists)
        let savedGateway = app.buttons.matching(
            NSPredicate(format: "label BEGINSWITH %@", "Personal Mac")
        ).firstMatch
        XCTAssertTrue(savedGateway.exists)
        XCTAssertTrue(savedGateway.isHittable)
        savedGateway.tap()
        XCTAssertTrue(app.staticTexts["Choose your Fabric"].exists)
    }

    func testDeniedCameraStateOffersRecoveryAndManualFallback() {
        let app = launchFixture("scanner-denied")

        XCTAssertTrue(app.staticTexts["Camera access is off"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.buttons["Open Settings"].exists)
        XCTAssertTrue(app.buttons["Use Advanced setup"].exists)
        XCTAssertTrue(app.buttons["Cancel"].exists)
    }

    func testAdvancedSetupClearsManualTokenWhenEndpointChanges() {
        let app = launchFixture("onboarding")
        app.buttons["Advanced setup"].tap()

        let address = app.textFields["Fabric server address"]
        let token = app.secureTextFields["Session token"]
        XCTAssertTrue(address.waitForExistence(timeout: 4))
        XCTAssertTrue(token.exists)

        address.tap()
        address.typeText("https://gateway-a.example.test")
        token.tap()
        token.typeText("endpoint-a-secret")
        let save = app.buttons["Save and connect"]
        XCTAssertTrue(save.isEnabled)

        address.tap()
        address.typeKey("a", modifierFlags: .command)
        address.typeText("https://gateway-b.example.test")

        XCTAssertFalse(save.isEnabled, "A credential authorized for gateway A must not survive an edit to gateway B.")
    }

    func testConnectionHandoffExplainsExecutionBeforeHome() {
        let app = launchFixture("connection-success")

        XCTAssertTrue(app.staticTexts["Ready on Personal Mac"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Fabric runs on this gateway"].exists)
        XCTAssertTrue(app.staticTexts["Keep the gateway online"].exists)
        XCTAssertTrue(app.buttons["Continue to Fabric"].exists)
    }

    func testLegacyConnectionHandoffNeverClaimsVerifiedContinuity() {
        let app = launchFixture("connection-legacy")

        XCTAssertTrue(app.staticTexts["Ready on Personal Mac"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Execution location not verified"].exists)
        XCTAssertTrue(app.staticTexts["Disconnect behavior not verified"].exists)
        XCTAssertFalse(app.staticTexts["You can leave the app"].exists)
    }

    func testSessionsFixtureShowsTheCompleteLibraryHierarchy() {
        let app = launchFixture("sessions")

        XCTAssertTrue(app.navigationBars["Personal Mac"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Pinned on this device"].exists)
        XCTAssertTrue(app.staticTexts["Active now"].exists)
        XCTAssertTrue(app.staticTexts["Recent sessions"].exists)
        XCTAssertTrue(app.staticTexts["Ship the next TestFlight build"].exists)
    }

    func testSettingsFixtureExposesDiagnosticsAndOffboarding() {
        let app = launchFixture("settings")

        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Connection"].exists)

        let diagnostics = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[c] %@", "Diagnostics")
        ).firstMatch
        scrollTo(diagnostics, in: app)
        diagnostics.tap()
        XCTAssertTrue(app.navigationBars["Diagnostics"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Safe to review before sharing"].exists)
        let copy = app.buttons["Copy redacted report"]
        scrollTo(copy, in: app)
        copy.tap()
        XCTAssertTrue(app.buttons["Copied redacted report"].waitForExistence(timeout: 2))
        app.navigationBars["Diagnostics"].buttons.firstMatch.tap()

        let serverManagement = app.staticTexts["Server management"]
        scrollTo(serverManagement, in: app)
        XCTAssertTrue(serverManagement.exists)

        let switchServer = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[c] %@", "Switch server")
        ).firstMatch
        scrollTo(switchServer, in: app)
        switchServer.tap()
        XCTAssertTrue(app.staticTexts["Switch servers?"].waitForExistence(timeout: 3))
        let confirmSwitch = app.buttons["Switch Servers"]
        XCTAssertTrue(confirmSwitch.exists)
        confirmSwitch.tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 3))

        let forgetServer = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[c] %@", "Forget this server")
        ).firstMatch
        scrollTo(forgetServer, in: app)
        forgetServer.tap()
        XCTAssertTrue(app.staticTexts["Forget this server?"].waitForExistence(timeout: 3))
        let confirmForget = app.buttons["Forget Server"]
        XCTAssertTrue(confirmForget.exists)
        confirmForget.tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 3))
    }

    func testChatActivityFixtureShowsReasoningToolsAndApprovalChoices() {
        let app = launchFixture("chat-activity")

        XCTAssertTrue(app.navigationBars["Release readiness"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.staticTexts["Reasoning"].exists)
        XCTAssertTrue(app.staticTexts["xcodebuild"].exists)
        XCTAssertTrue(app.staticTexts["Approval needed"].exists)
        let allowOnce = app.buttons["Allow once"]
        XCTAssertTrue(allowOnce.exists)
        XCTAssertTrue(app.buttons["Deny"].exists)
        XCTAssertTrue(app.staticTexts["Always is unavailable because this request requires an explicit approval each time."].exists)

        allowOnce.tap()
        XCTAssertFalse(allowOnce.isEnabled)

        XCTAssertTrue(app.buttons["Commands"].exists)
        XCTAssertTrue(app.buttons["Run draft in background"].exists)
        XCTAssertTrue(app.buttons["Processes"].exists)
        XCTAssertTrue(app.buttons["Live View"].exists)
        XCTAssertTrue(app.textFields["chat-composer"].exists)

        app.buttons["Send message"].tap()
        XCTAssertTrue(app.staticTexts["Prepare the verified build notes"].waitForExistence(timeout: 2))
    }

    /// Opt-in production-wiring smoke against a disposable source gateway.
    /// The test-runner environment provides a one-use pairing URL; this test
    /// never includes it in arguments, assertion messages, attachments, or logs.
    func testDisposableGatewayPairingReachesTheRealConnectedShell() throws {
        guard
            let pairingURL = ProcessInfo.processInfo.environment["FABRIC_TEST_GATEWAY_PAIRING_URL"],
            !pairingURL.isEmpty
        else {
            throw XCTSkip("Disposable Fabric gateway pairing is not configured")
        }

        let app = XCUIApplication()
        addTeardownBlock { app.terminate() }
        app.launchEnvironment["FABRIC_E2E_PAIRING_URL"] = pairingURL
        app.launchArguments = [
            "-UIPreferredContentSizeCategoryName",
            "UICTContentSizeCategoryL",
            "-AppleLanguages", "(en)",
            "-AppleLocale", "en_US",
        ]
        app.launch()

        let ready = app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH %@", "Ready on ")
        ).firstMatch
        XCTAssertTrue(ready.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Fabric runs on this gateway"].exists)

        app.buttons["Continue to Fabric"].tap()
        XCTAssertTrue(app.staticTexts["What should we get done?"].waitForExistence(timeout: 8))

        app.buttons["Sessions"].tap()
        XCTAssertTrue(app.staticTexts["Recent sessions"].waitForExistence(timeout: 8))

        app.buttons["Settings"].tap()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Connection"].exists)

        app.buttons["Home"].tap()
        XCTAssertTrue(app.staticTexts["What should we get done?"].waitForExistence(timeout: 5))
    }

    func testChatBlockingInteractionRemainsReachableAtAccessibilityTextSizes() {
        let app = XCUIApplication()
        app.launchArguments = [
            "-fabric-ui-fixture", "chat-activity",
            "-UIPreferredContentSizeCategoryName",
            "UICTContentSizeCategoryAccessibilityXXXL",
            "-AppleLanguages", "(en)",
            "-AppleLocale", "en_US",
        ]
        app.launch()

        XCTAssertTrue(app.staticTexts["Approval needed"].waitForExistence(timeout: 4))
        let allowOnce = app.buttons["Allow once"]
        let controlDock = app.scrollViews["chat-interaction-dock-scroll"]
        XCTAssertTrue(controlDock.waitForExistence(timeout: 2))
        scrollTo(allowOnce, in: app, preferredScrollView: controlDock)
        XCTAssertTrue(allowOnce.isHittable)
        allowOnce.tap()
        let fixtureStatus = app.staticTexts["chat-fixture-status"]
        XCTAssertTrue(fixtureStatus.waitForExistence(timeout: 2))
        XCTAssertEqual(fixtureStatus.label, "Approval response: Once")

        for label in ["Commands", "Run draft in background", "Processes", "Live View"] {
            let action = app.buttons[label]
            scrollTo(action, in: app, preferredScrollView: controlDock)
            XCTAssertTrue(action.isHittable, "\(label) must remain reachable at AX XXXL")
        }

        let composer = app.textFields["chat-composer"]
        scrollTo(composer, in: app, preferredScrollView: controlDock)
        XCTAssertTrue(composer.isHittable)
        let send = app.buttons["Send message"]
        scrollTo(send, in: app, preferredScrollView: controlDock)
        XCTAssertTrue(send.isHittable)
        send.tap()
        XCTAssertTrue(app.staticTexts["Prepare the verified build notes"].waitForExistence(timeout: 2))
    }

    func testApprovedHomeFixtureStillLaunches() {
        let app = XCUIApplication()
        app.launchArguments = [
            "-fabric-home-fixture", "running",
            "-UIPreferredContentSizeCategoryName",
            "UICTContentSizeCategoryL",
            "-AppleLanguages", "(en)",
            "-AppleLocale", "en_US",
        ]
        app.launch()

        XCTAssertTrue(app.staticTexts["What should we get done?"].waitForExistence(timeout: 4))
        XCTAssertTrue(app.buttons["Start goal"].exists)
    }

    private func launchFixture(_ fixture: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "-fabric-ui-fixture", fixture,
            "-UIPreferredContentSizeCategoryName",
            "UICTContentSizeCategoryL",
            "-AppleLanguages", "(en)",
            "-AppleLocale", "en_US",
        ]
        app.launch()
        return app
    }

    private func scrollTo(
        _ element: XCUIElement,
        in app: XCUIApplication,
        preferredScrollView: XCUIElement? = nil,
        maximumSwipes: Int = 10,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        for _ in 0..<maximumSwipes {
            if element.exists, element.isHittable { return }
            let scrollView = preferredScrollView ?? app.scrollViews.firstMatch
            if scrollView.exists {
                scrollView.swipeUp()
            } else {
                app.swipeUp()
            }
        }
        XCTAssertTrue(
            element.exists && element.isHittable,
            "Could not scroll \(element) into view",
            file: file,
            line: line
        )
    }
}
