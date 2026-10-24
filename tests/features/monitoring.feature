@bdd
Feature: Monitor a website
  As a visitor I want my URL checked automatically
  so that I find out when it is down.

  Background:
    Given a clean monitoring service

  @VW-001
  Scenario: Registering a new URL runs a first check
    Given "https://example.com" answers with status 200 in 80 ms
    When I register "https://example.com"
    Then the response status is 201
    And the dashboard shows status "UP"
    And the dashboard lists 1 recent check

  @VW-001
  Scenario: Registering the same URL again does not duplicate it
    Given "https://example.com" is already monitored
    When I register "HTTPS://Example.com"
    Then the response status is 200
    And the number of monitored endpoints is 1

  @VW-002
  Scenario Outline: Unsafe or malformed URLs are refused
    When I register "<url>"
    Then the response status is 400
    And the error message is not empty
    And the number of monitored endpoints is 0

    Examples:
      | url                                       |
      | http://169.254.169.254/latest/meta-data/  |
      | http://127.0.0.1:9001/                    |
      | http://10.0.0.5/admin                     |
      | http://[::1]/                             |
      | file:///etc/passwd                        |
      | ftp://example.com/                        |
      | https://user:secret@example.com/          |
      | not a url                                 |

  @VW-003
  Scenario: The monitoring limit is enforced
    Given the monitoring limit is 1 endpoint
    And "https://example.com" is already monitored
    When I register "https://other.example.com"
    Then the response status is 429
    And the number of monitored endpoints is 1

  @VW-003
  Scenario: A URL that is already monitored still succeeds at the limit
    Given the monitoring limit is 1 endpoint
    And "https://example.com" is already monitored
    When I register "https://example.com"
    Then the response status is 200

  @VW-005
  Scenario Outline: Every scheduled check is classified
    Given "https://example.com" is already monitored
    And the next check of "https://example.com" answers with status <code> in <ms> ms
    When the scheduled check runs
    Then the dashboard for "https://example.com" shows status "<status>"

    Examples:
      | code | ms   | status   |
      | 200  | 120  | UP       |
      | 200  | 999  | UP       |
      | 200  | 1000 | DEGRADED |
      | 200  | 4500 | DEGRADED |
      | 503  | 40   | DOWN     |
      | 404  | 40   | DOWN     |
      | 301  | 40   | DOWN     |

  @VW-004
  Scenario: A disabled endpoint is not checked
    Given "https://example.com" is already monitored
    And "https://example.com" is disabled
    When the scheduled check runs
    Then the checker reports 0 endpoints checked

  @VW-004
  Scenario: Every enabled endpoint is checked
    Given "https://example.com" is already monitored
    And "https://other.example.com" is already monitored
    When the scheduled check runs
    Then the checker reports 2 endpoints checked
