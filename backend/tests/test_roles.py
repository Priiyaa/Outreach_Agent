import pytest

from app.services.roles import classify_cs_role, is_excluded_title, tech_terms

PYTHON_JD = "You will build APIs and data pipelines in Python and SQL, deployed on AWS."


@pytest.mark.parametrize("title", [
    "Software Engineer", "Full Stack Engineer", "Full-Stack Developer", "Senior Engineer, Full-Stack - Forge (R6244)",
    "Machine Learning Engineer", "AI Engineer", "Research Scientist Graduate - 2027", "Member of Technical Staff - SDK",
    "Data Engineer", "Site Reliability Engineer", "Security Engineer", "Forward Deployed Engineer", "Build Engineer II",
    "GenAI Engineer (Python)", "iOS Engineer", "Embedded Software Engineer", "Electrical Systems Software Engineer",
])
def test_tech_titles_are_kept_on_title_alone(title):
    match, evidence = classify_cs_role(title, "", "")
    assert match and evidence.startswith("title:")


@pytest.mark.parametrize("title", [
    "Tier 1 Help Desk", "Level 1 Help Desk", "Senior Sales Engineer", "Technical Program Manager (TPM)",
    "Staff Technical Program Manager, Infrastructure Security", "Senior Technical Recruiter", "Senior Accountant",
    "Technical Support Engineer, Metronome", "Software Sales Engineer", "Account Executive, Security Software",
    "Senior Electrical Engineer", "Manufacturing Engineer II", "Product Quality Engineer I", "Mechanical Engineer, High Speed Missiles",
    "FPGA Engineer", "Fraud Investigator", "AI Training Contributor - Balochi - Remote", "Generative AI Associate - Flexible Hours",
    "Engineering Test Technician", "Salesforce Account Manager", "Associate Product Manager, Hive Models",
])
def test_non_tech_titles_are_rejected_even_when_the_description_sounds_technical(title):
    assert not classify_cs_role(title, "Engineering", PYTHON_JD)[0]


def test_description_alone_needs_an_engineerish_title_and_several_technologies():
    match, evidence = classify_cs_role("Business Operations Analyst", "Operations", PYTHON_JD)
    assert match and evidence.startswith("description:") and "python" in evidence
    assert not classify_cs_role("Operations Manager", "", PYTHON_JD)[0]  # title names no builder
    assert not classify_cs_role("Business Analyst", "", "Build APIs, databases, and Linux scripts with git.")[0]  # no language
    assert not classify_cs_role("Business Analyst", "", "Our platform helps teams build software.")[0]


def test_department_counts_only_for_engineerish_titles():
    assert classify_cs_role("Engineer", "Machine Learning", "")[1] == "department: Machine Learning"
    assert not classify_cs_role("Office Lead", "Machine Learning", "")[0]


def test_tech_terms_count_plurals_and_variants_once():
    assert tech_terms("Algorithms and algorithm design; databases, a database; C++ and c++") == ["algorithms", "databases", "c++"]
    assert tech_terms("She goes to the gym") == []


def test_excluded_title_helper():
    assert is_excluded_title("Sales Engineer") and not is_excluded_title("Salesforce Developer")


@pytest.mark.parametrize("title", ["ServiceNow Developer", "Drupal Developer", "APEX Developer (Top Secret Clearance Required)",
                                   "Cloud and Storage Engineer", "React Developer"])
def test_platform_prefixed_developer_titles_are_kept(title):
    assert classify_cs_role(title, "", "")[0]


def test_developer_without_a_tech_prefix_is_not_enough():
    assert not classify_cs_role("Real Estate Developer", "", "")[0]
