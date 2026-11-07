@bdd
Feature: An honest checker
  As an owner I want VigilWatch to say "I cannot tell" when its own connection is broken,
  so that a monitoring fault is never reported as your website being down.

  Background:
    Given a clean monitoring service
    And alert emails are captured
    And control URLs are configured
    And "https://example.com" is already monitored

  @VW-022 @negative
  Scenario: A blind checker does not accuse the website
    Given the checker cannot reach the internet for 3 checks
    And the next 3 checks of "https://example.com" answer with status 503 in 40 ms
    When the scheduled check runs 3 times
    Then the number of alerts sent is 0
    And "https://example.com" has 0 incidents
    And the failure count of "https://example.com" is 0
    And the dashboard for "https://example.com" shows status "INCONCLUSIVE"

  @VW-022
  Scenario: A real outage is still reported when the checker can see the internet
    Given the checker can reach the internet for 2 checks
    And the next 2 checks of "https://example.com" answer with status 503 in 40 ms
    When the scheduled check runs 2 times
    Then the number of alerts sent is 1
    And alert 1 has a subject starting "[VigilWatch] DOWN"
    And "https://example.com" has 1 open incident
    And the dashboard for "https://example.com" shows status "DOWN"

  @VW-022
  Scenario: A blind cycle between two failures neither counts nor erases them
    Given the checker can reach the internet for 1 check
    And the checker cannot reach the internet for 1 check
    And the checker can reach the internet for 1 check
    And the next 3 checks of "https://example.com" answer with status 503 in 40 ms
    When the scheduled check runs 3 times
    Then the number of alerts sent is 1
    And "https://example.com" has 1 open incident

  @VW-022
  Scenario: An open incident survives a blind cycle and closes on genuine recovery
    Given the checker can reach the internet for 2 checks
    And the checker cannot reach the internet for 1 check
    And the next 3 checks of "https://example.com" answer with status 503 in 40 ms
    And the next check of "https://example.com" answers with status 200 in 90 ms
    When the scheduled check runs 4 times
    Then the number of alerts sent is 2
    And alert 1 has a subject starting "[VigilWatch] DOWN"
    And alert 2 has a subject starting "[VigilWatch] RECOVERED"
    And "https://example.com" has 1 resolved incident

  @VW-022
  Scenario: A healthy target proves the checker is connected, so nothing is doubted
    Given "https://other.example.com" is already monitored
    And the checker cannot reach the internet for 2 checks
    And the next 2 checks of "https://example.com" answer with status 503 in 40 ms
    When the scheduled check runs 2 times
    Then the number of alerts sent is 1
    And "https://example.com" has 1 open incident
    And "https://other.example.com" has 0 incidents
