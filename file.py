import os
import re
import time
import traceback
from datetime import datetime, timedelta
from getpass import getpass

from selenium import webdriver
from selenium.common.exceptions import (
    NoAlertPresentException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


COURSE_SELECTION_URL = "https://sys.ndhu.edu.tw/AA/CLASS/subjselect/course_sele.aspx"
ADD_BUTTON_SELECTOR = "input.add[value='加選']"
COURSE_ID_PATTERN = re.compile(r"ss\(this,(\d+),")
FALLBACK_CLICK_LEAD_SECONDS = 0.1
LATENCY_TEST_TIMEOUT_SECONDS = 10


def create_driver() -> webdriver.Chrome:
    """Create a Chrome driver and open the course selection page."""
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=options)
    driver.get(COURSE_SELECTION_URL)
    return driver


def auto_login(driver: webdriver.Chrome) -> None:
    """Log in using environment variables or secure interactive prompts."""
    student_id = os.getenv("NDHU_STUDENT_ID") or input("Student ID: ").strip()
    password = os.getenv("NDHU_COURSE_PASSWORD") or getpass(
        "Course selection password: "
    )

    wait = WebDriverWait(driver, 20)
    student_id_input = wait.until(
        EC.element_to_be_clickable((By.ID, "ContentPlaceHolder1_ed_StudNo"))
    )
    password_input = driver.find_element(By.ID, "ContentPlaceHolder1_ed_pass")

    student_id_input.send_keys(student_id)
    password_input.send_keys(password)
    driver.find_element(By.ID, "ContentPlaceHolder1_BtnLoginNew").click()
    print("Login submitted. Complete any browser prompts if needed.")


def get_visible_course_ids(driver: webdriver.Chrome) -> list[str]:
    """Return course IDs for the visible add buttons currently on the page."""
    course_ids = []
    for button in driver.find_elements(By.CSS_SELECTOR, ADD_BUTTON_SELECTOR):
        if not button.is_displayed() or not button.is_enabled():
            continue

        onclick = button.get_attribute("onclick") or ""
        match = COURSE_ID_PATTERN.search(onclick)
        if match:
            course_ids.append(match.group(1))

    return course_ids


def accept_alert_if_present(driver: webdriver.Chrome, course_id: str) -> None:
    """Accept an alert after a course click, if one appears."""
    try:
        alert = WebDriverWait(driver, 1).until(EC.alert_is_present())
        print(f"Course {course_id}: {alert.text}")
        alert.accept()
    except (NoAlertPresentException, TimeoutException):
        print(f"Course {course_id}: no alert appeared.")


def measure_first_course_latency(
    driver: webdriver.Chrome, course_ids: list[str]
) -> float | None:
    """Click the first add button and measure the time until its alert appears."""
    course_id = course_ids[0]
    selector = f"input.add[value='加選'][onclick*='ss(this,{course_id},']"

    try:
        button = driver.find_element(By.CSS_SELECTOR, selector)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        print(f"Testing response latency with the first 加選 record, course {course_id}...")
        started_at = time.perf_counter()
        button.click()
        alert = WebDriverWait(driver, LATENCY_TEST_TIMEOUT_SECONDS).until(
            EC.alert_is_present()
        )
        latency_seconds = time.perf_counter() - started_at
        print(f"Course {course_id}: {alert.text}")
        print(f"Measured click-to-alert latency: {latency_seconds * 1000:.0f} ms")
        alert.accept()
        return latency_seconds
    except (NoSuchElementException, StaleElementReferenceException):
        print(f"Course {course_id}: add button is no longer available for latency testing.")
    except (NoAlertPresentException, TimeoutException):
        print(
            f"Course {course_id}: no alert appeared within "
            f"{LATENCY_TEST_TIMEOUT_SECONDS} seconds."
        )

    return None


def click_courses(driver: webdriver.Chrome, course_ids: list[str]) -> None:
    """Click each snapshotted course add button once."""
    for course_id in course_ids:
        selector = f"input.add[value='加選'][onclick*='ss(this,{course_id},']"
        try:
            button = driver.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            button.click()
            accept_alert_if_present(driver, course_id)
        except (NoSuchElementException, StaleElementReferenceException):
            print(f"Course {course_id}: add button is no longer available.")

        time.sleep(0.1)


def get_target_time(click_lead_seconds: float) -> tuple[datetime, datetime]:
    """Prompt for a target time and return its adjusted click time."""
    while True:
        target_time_text = input("Enter click time (HH:MM:SS): ").strip()
        try:
            target_clock_time = datetime.strptime(target_time_text, "%H:%M:%S").time()
        except ValueError:
            print("Invalid time. Use HH:MM:SS, for example 09:00:00.")
            continue

        target_time = datetime.combine(datetime.now().date(), target_clock_time)
        adjusted_target_time = target_time - timedelta(seconds=click_lead_seconds)
        if adjusted_target_time <= datetime.now():
            print("That adjusted click time has already passed today. Enter a later time.")
            continue

        return target_time, adjusted_target_time


def wait_until(target_time: datetime) -> None:
    """Wait until the target time while displaying the current time."""
    print(f"Waiting until {target_time.strftime('%H:%M:%S')}...")
    while True:
        now = datetime.now()
        print(f"Current time: {now.strftime('%H:%M:%S.%f')[:-3]}", end="\r", flush=True)
        if now >= target_time:
            print()
            return
        time.sleep(0.001)


def main() -> None:
    driver = create_driver()
    try:
        auto_login(driver)

        input(
            "After login, show the course list containing the buttons you want, "
            "then press Enter to test latency using the first visible 加選 button..."
        )
        course_ids = get_visible_course_ids(driver)

        if not course_ids:
            print("No visible 加選 buttons were found.")
        else:
            tested_course_id = course_ids[0]
            measured_latency = measure_first_course_latency(driver, course_ids)
            click_lead_seconds = (
                measured_latency
                if measured_latency is not None
                else FALLBACK_CLICK_LEAD_SECONDS
            )
            if measured_latency is None:
                print(
                    "Using fallback click lead time: "
                    f"{FALLBACK_CLICK_LEAD_SECONDS:.3f} seconds."
                )

            course_ids = get_visible_course_ids(driver)
            if measured_latency is not None:
                course_ids = [
                    course_id
                    for course_id in course_ids
                    if course_id != tested_course_id
                ]

            if not course_ids:
                print("No visible 加選 buttons remain after the latency test.")
            else:
                print(f"Prepared {len(course_ids)} remaining course button(s).")
                target_time, adjusted_target_time = get_target_time(click_lead_seconds)
                print(f"Requested time: {target_time.strftime('%H:%M:%S.%f')[:-3]}")
                print(
                    "Actual click time: "
                    f"{adjusted_target_time.strftime('%H:%M:%S.%f')[:-3]} "
                    f"({click_lead_seconds:.3f} seconds earlier)"
                )
                wait_until(adjusted_target_time)
                print(f"Clicking {len(course_ids)} course button(s)...")
                click_courses(driver, course_ids)
                print("Finished clicking the visible course buttons.")
    except Exception:
        print("\nThe script stopped because of an error:")
        traceback.print_exc()

    input("Press Enter to exit the script (Chrome stays open).")


if __name__ == "__main__":
    main()
