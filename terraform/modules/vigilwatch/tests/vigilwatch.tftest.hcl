
run "a_small_global_cap_needs_no_per_user_setting" {
  command = apply

  variables {
    max_endpoints = 3
  }

  assert {
    condition     = output.max_endpoints_per_user == 3
    error_message = "the per-user cap defaults to min(5, max_endpoints), so lowering max_endpoints alone still plans"
  }
}

run "the_per_user_cap_defaults_to_five_below_the_global_cap" {
  command = apply

  assert {
    condition     = output.max_endpoints_per_user == 5
    error_message = "five endpoints per user unless set"
  }
}

run "refuses_a_cors_origin_that_cannot_be_a_sign_in_redirect" {
  command = plan

  variables {
    extra_cors_origins = ["http://127.0.0.1:8080"]
  }
  expect_failures = [var.extra_cors_origins]
}

run "refuses_a_cors_origin_with_a_trailing_slash" {
  command = plan

  variables {
    extra_cors_origins = ["https://example.com/"]
  }
  expect_failures = [var.extra_cors_origins]
}
