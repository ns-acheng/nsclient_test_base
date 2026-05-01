# NPLAN-6711: [WIP] NPLAN-6711 Auto re-enable NS Client after Disable Test Plan

## Source
- Confluence: [[WIP] NPLAN-6711 Auto re-enable NS Client after Disable Test Plan](https://netskope.atlassian.net/wiki/spaces/CDTBA/pages/7875198997)
- Page ID: 7875198997
- Date fetched: 2026-05-01

## Feature Description
This feature adds an optional auto re-enable timer to the "Disable All Client Services" functionality. When configured, the Netskope Client will automatically re-enable all services after a specified duration.

## Current State
- Disable All Client Services : Permanently disables ALL client services until manually re-enabled
- Master Password : Optional authentication to allow/prevent disabling (Windows/macOS only)
- One-Time Password (OTP) : Already has timer support - disable individual services with auto-re-enable

## New Capability
Add optional auto re-enable timer to "Disable All Client Services" action. The timer applies regardless of whether master password authentication is used.

## Key Distinction
- Master Password (when enabled): Authenticates the disable action (optional security gate)
- Auto Re-enable Timer : Automatically re-enables services after configured duration (independent feature)

## Duration range
- 30 minutes to 24 hours

## Control Flags and Feature Flags
Control Flag NPLAN6711_AUTO_REENABLE_NS_CLIENT_AFTER_DISABLEMENT
Feature Flag nplan6711_auto_reenable_ns_client_after_disablement

## Goal
- Validate that NS Client correctly enables and enforces FIPS Mode (Strict and Permissive) on Windows and macOS for NS Agent and NS Service
- Ensure FIPS provider loading, self‑tests, and runtime conditional tests behave as designed.

## Scope
The testing covers all relevant endpoint platforms:
- Windows
- MacOS
- Linux

## Out of Scope
- iOS, Android and ChromeOS supporting

## Status
- Test completion: Windows - 0% (0/54)
- Test Status Example: PASSGreen FAILRed NAYellow BlockPurple Win PASSGreen Mac PASSYellow Linux PASSBlue

## Test Automation
Automate the p0 test cases.

## Integration Testing
- Validate integration with:NPAEPDLPDEM

## E2E Performance Testing
No specific requirements for the Central QE / Solutions QE team

## E2E Functional / Customer Scenario Testing
No specific requirements for the Central QE / Solutions QE team

## Release Schedule
Beta: Jun 2026 / R139
GA: Aug 2026 / R141

## Test Cases

### A01: Set Auto Re-enable duration to 3 minutes
- **Priority**: P0
- **Steps**:
  1. The duration value can be saved
  2. Check nsconfig.json : clientAllDisable.autoReenableDuration = 3
  3. Check nsuser.conf about the end time
  4. observe that the nsclient auto enabled once the timer expires
  5. observe the client enabled status is uploaded to the tenant

### A02: Set Auto Re-enable duration to 10 minutes with OTP
- **Priority**: P0
- **Platform**: Windows, macOS
- **Steps**:
  1. The duration value and the OTP can be saved
  2. Check nsconfig.json : clientAllDisable.autoReenableDuration = 10
  3. Check nsuser.conf about the end time
  4. observe that the timer starts when the OTP is input
  5. observe that the nsclient auto enabled once the timer expires
  6. observe the client enabled status is uploaded to the tenant

### A03: Set FF nplan6711_auto_reenable_ns_client_after_disablement = 0
- **Priority**: P1
- **Steps**:
  1. No Auto Re-enable duration shows in the Web UI
  2. Check nsconfig.json : No clientAllDisable.autoReenableDuration
  3. observe that no timer is set for the client service disablement

### B01: Set FF encryptClientConfig = 1 with the setting Auto Re-enable duration to 3 minutes
- **Priority**: P1
- **Steps**:
  1. Ensure the timer can work as expected

### B02: Trigger the timer and reboot/shutdown.
- **Steps**:
  1. If boot time is before the timer expired, make sure the timer can work continuously.
  2. If boot time is after the timer expired, make sure the client service re-enabled right after booting.

### B03: Trigger the timer and put the system to sleep
- **Steps**:
  1. If resume time is before the timer expired, make sure the timer can work continuously.
  2. If resume time is after the timer expired, make sure the client service re-enabled right after rebooting.

### B04: Trigger the timer and put the system to S0 modern standby
- **Platform**: Windows
- **Steps**:
  1. If resume time is before the timer expired, make sure the timer can work continuously.
  2. If resume time is after the timer expired, make sure the client service re-enabled right after rebooting.

### B05: Trigger the timer and put the system to hibernate
- **Platform**: Windows
- **Steps**:
  1. If resume time is before the timer expired, make sure the timer can work continuously.
  2. If resume time is after the timer expired, make sure the client service re-enabled right after rebooting.

### B06: Trigger the timer and set auto upgrade target to within timer period
- **Priority**: P1
- **Steps**:
  1. Make sure auto upgrade can work, NOT impacted by the timer
  2. Make sure client services are enabled after upgrade (Timer is cleaned)

### B07: Trigger the timer and set auto upgrade target to the time when timer expired
- **Priority**: P1
- **Steps**:
  1. Make sure auto upgrade can work, NOT impacted by the timer
  2. Make sure client services are enabled after upgrade (Timer is cleaned)

### B08: Trigger the timer. Try to stop the client service by sc stop or kill the process.
- **Steps**:
  1. Restart the client when the timer is not expired → check the timer can continue to work
  2. Restart the client after the timer is expired -> see client services are enabled

### B09: Trigger the timer. Try to kill the client service with stwatchdog running. The client service will be auto restarted in 60 seconds.
- **Priority**: P1
- **Steps**:
  1. The client gets restarted when the timer is not expired → check the timer can continue to work
  2. The client get restarted after the timer is expired -> see client services are enabled

### T01: Timer duration is across to another day.

### T02: Timer is set but the user update the time zone to earlier.

### T03: Timer is set but the user update the time zone to later.

### R01: Set secure enrollment and secure encryption with the setting Auto Re-enable duration to 3 minutes
- **Steps**:
  1. Ensure the timer can work as expected
  2. Ensure the tunnel can be established when client re-enabled

### R02: Set Auto Re-enable duration to 10 minutes with OTP.
- **Steps**:
  1. Ensure the client services are not disabled
  2. Ensure the timer is not triggered

### R03: Set Auto Re-enable duration to 10 minutes in multiple user platform.
- **Platform**: Windows
- **Steps**:
  1. observe the client is enabled on time for each user
