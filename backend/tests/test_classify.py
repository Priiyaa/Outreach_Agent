from app.services.classify import (
    classify_cs_role,
    classify_experience,
    company_key,
    detect_sponsorship,
    is_internship,
    is_us_location,
    years_required,
)


def test_experience_rules():
    f = classify_experience
    assert f("Software Engineer, New Grad 2026", "", "greenhouse")[0] == "New grad"
    assert f("Senior Data Engineer", "new grads welcome", "greenhouse")[0] == "Experienced"  # title wins
    assert f("Software Engineer II", "", "lever")[0] == "New grad"
    assert f("Software Engineer III", "", "lever")[0] == "Experienced"
    assert f("Staff Engineer", "", "lever")[0] == "Experienced"
    assert f("Analyst", "", "jobright")[0] == "New grad"  # lists are new-grad lists
    assert f("Data Analyst", "3+ years of experience with SQL", "greenhouse")[0] == "Experienced"
    assert f("Data Analyst", "2 years of experience with SQL", "greenhouse")[0] == "New grad"
    assert f("Business Analyst", "We love people", "greenhouse") == ("Unclear", "")


def test_cs_role_uses_description_for_misleading_titles():
    match, evidence = classify_cs_role(
        "Business Operations Analyst", "Operations",
        "Build internal APIs and automate data pipelines using Python. Maintain services used by the team.",
    )
    assert match and evidence.startswith("description:")
    assert not classify_cs_role(
        "Business Operations Analyst", "Operations",
        "Coordinate vendor schedules, budgets, and quarterly business reviews. Familiarity with office software is preferred.",
    )[0]


def test_years_required_prefers_required_over_preferred():
    assert years_required("5+ years of experience preferred.\n1 year of experience required.") == 1
    assert years_required("3-5 years of experience") == 3
    assert years_required("preferred: 6 years of experience") == 6
    assert years_required("") is None


def test_internship_is_not_internal():
    assert is_internship("Software Engineer Intern") and is_internship("Data Co-op")
    assert not is_internship("Internal Tools Engineer")


def test_us_location_keeps_unknown_and_remote():
    for loc in ["Chicago, IL", "Remote", "", "Remote - US", "New York"]:
        assert is_us_location(loc), loc
    for loc in ["London, UK", "Toronto, Canada", "Bengaluru, India"]:
        assert not is_us_location(loc), loc


def test_sponsorship_detection():
    assert detect_sponsorship("We do not offer visa sponsorship") == "No"
    assert detect_sponsorship("Visa sponsorship available") == "Yes"
    assert detect_sponsorship("nothing here") is None
    assert detect_sponsorship("", "Sponsorship: Offers Sponsorship") == "Yes"
    assert detect_sponsorship("", "Sponsorship: U.S. Citizenship is Required") == "No"


def test_export_control_and_citizens_only_wording_means_no_sponsorship():
    spacex = ("ITAR REQUIREMENTS: To conform to U.S. Government export regulations, applicant must be a (i) U.S. citizen "
              "or national, (ii) U.S. lawful, permanent resident (aka green card holder)")
    assert detect_sponsorship(spacex) == "No"
    assert detect_sponsorship("Position Restriction: This position is restricted to US citizens or lawful permanent residents") == "No"
    assert detect_sponsorship("Currently a US Citizen with capability to obtain and maintain a US Q clearance.") == "No"
    assert detect_sponsorship("We hire globally and welcome international candidates.") is None
    cloudflare = ("any offer of employment may be conditioned on your authorization to receive software or technology "
                  "controlled under these U.S. export laws without sponsorship for an export license.")
    assert detect_sponsorship(cloudflare) is None  # about export licenses, not visas


def test_company_key():
    assert company_key("Stripe, Inc.") == "stripe" == company_key("STRIPE")


def test_more_foreign_locations_are_caught_without_losing_us_namesakes():
    for loc in ["Costa Rica", "Stuttgart", "Cape Town", "Budapest", "Yerevan", "Kuwait City, Kuwait", "Taipei",
                "Croatia - Zagreb", "Hub - Porto", "São Paulo", "Remote or Mississauga", "United Kingdon"]:
        assert not is_us_location(loc), loc
    for loc in ["Manchester, NH", "Athens, GA", "Lima, OH", "San Francisco", "Remote, Global", "Home based - Worldwide"]:
        assert is_us_location(loc), loc


def test_now_or_in_the_future_wording_means_no_sponsorship():
    from app.services.classify import detect_sponsorship
    no = [
        "Applicants for employment in the US must have work authorization that does not now or in the future require "
        "sponsorship of a visa for employment authorization in the United States.",  # Accenture
        "Candidates must be authorized to work in the US without requiring sponsorship.",
        "You must be legally authorized to work in the U.S. and not require employer sponsorship now or in the future.",
        "Applicants must not now or in the future require visa sponsorship.",
    ]
    assert [detect_sponsorship(t) for t in no] == ["No"] * len(no)
    # the bare application question says nothing either way
    assert detect_sponsorship("Will you now or in the future require sponsorship for employment visa status?") is None
    assert detect_sponsorship("We sponsor H-1B visas. Will you now or in the future require sponsorship?") == "Yes"
