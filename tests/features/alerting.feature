@bdd
Feature: Alerts without noise
  As an owner I want one email when a site goes down and one when it recovers,
  and nothing for a momentary blip.

  Background:
    Given a clean monitoring service
    And alert emails are captured
    And "https://example.com" is already monitored

  @VW-009 @negative
  Scenario: A single failed check does not alert
    Given the next check of "https://example.com" answers with status 503 in 40 ms
    When the scheduled check runs
    Then the number of alerts sent is 0
    And "https://example.com" has 0 incidents

  @VW-009 @VW-010
  Scenario: Two consecutive failures open an incident and alert once
    Given the next 3 checks of "https://example.com" answer with status 503 in 40 ms
    When the scheduled check runs 3 times
    Then the number of alerts sent is 1
    And alert 1 has a subject starting "[VigilWatch] DOWN"
    And "https://example.com" has 1 open incident
    And the dashboard for "https://example.com" shows status "DOWN"

  @VW-010
  Scenario: Recovery closes the incident and sends a recovery email
    Given the next 2 checks of "https://example.com" answer with status 503 in 40 ms
    And the next check of "https://example.com" answers with status 200 in 90 ms
    When the scheduled check runs 3 times
    Then the number of alerts sent is 2
    And alert 1 has a subject starting "[VigilWatch] DOWN"
    And alert 2 has a subject starting "[VigilWatch] RECOVERED"
    And "https://example.com" has 1 resolved incident
    And the dashboard for "https://example.com" shows status "UP"
    And the dashboard for "https://example.com" shows a last alert time

  @VW-009 @negative
  Scenario: A blip between successes never reaches the threshold
    Given the next check of "https://example.com" answers with status 503 in 40 ms
    And the next check of "https://example.com" answers with status 200 in 90 ms
    And the next check of "https://example.com" answers with status 503 in 40 ms
    When the scheduled check runs 3 times
    Then the number of alerts sent is 0
    And "https://example.com" has 0 incidents

  @VW-010
  Scenario: Incidents are still recorded when no alert topic is configured
    Given no alert topic is configured
    And the next 2 checks of "https://example.com" answer with status 503 in 40 ms
    When the scheduled check runs 2 times
    Then "https://example.com" has 1 open incident
    And the number of alerts sent is 0
