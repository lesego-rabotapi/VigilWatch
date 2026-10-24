@bdd
Feature: Read the status of a monitored URL
  As a visitor I want the dashboard to show how my site has been doing.

  Background:
    Given a clean monitoring service

  @VW-012
  Scenario: Asking about a URL that is not monitored
    When I ask for the status of "https://never-registered.example.org/"
    Then the response status is 404
    And the error message is not empty

  @VW-012
  Scenario: Asking without a URL
    When I ask for the status without a url
    Then the response status is 400
    And the error message is not empty

  @VW-012
  Scenario Outline: Asking with an unusable URL
    When I ask for the status of "<url>"
    Then the response status is 400
    And the error message is not empty

    Examples:
      | url                    |
      | ftp://example.com/     |
      | javascript:alert(1)    |
      | https://u:p@example.com |

  @VW-007 @VW-008 @VW-011
  Scenario: The payload reflects the recorded history
    Given "https://example.com" is already monitored
    And the next check of "https://example.com" answers with status 200 in 120 ms
    And the next check of "https://example.com" answers with status 503 in 40 ms
    When the scheduled check runs 2 times
    And I ask for the status of "https://example.com"
    Then the response status is 200
    And the dashboard lists 3 recent checks
    And uptime is 66.67 percent
    And the latest recent check is "DOWN"

  @VW-007
  Scenario: A DEGRADED check still counts as up
    Given "https://example.com" is already monitored
    And the next check of "https://example.com" answers with status 200 in 2500 ms
    When the scheduled check runs
    And I ask for the status of "https://example.com"
    Then uptime is 100.00 percent
