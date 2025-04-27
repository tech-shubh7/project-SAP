import requests
import pytest
from datetime import datetime, timedelta
import uuid

class AttendanceAPITester:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.user_data = None

    def run_test(self, name, method, endpoint, expected_status, data=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    return success, response.json()
                except:
                    return success, {}
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"Response: {response.text}")
                return False, {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_registration(self):
        """Test user registration"""
        test_id = str(uuid.uuid4())[:8]
        self.user_data = {
            "name": f"Test Student {test_id}",
            "email": f"test{test_id}@example.com",
            "password": "Test123!",
            "enrollment_number": f"EN{test_id}",
            "branch": "Computer Science",
            "year": 2,
            "role": "student"
        }
        
        success, response = self.run_test(
            "User Registration",
            "POST",
            "register",
            200,
            data=self.user_data
        )
        return success

    def test_login(self):
        """Test login functionality"""
        if not self.user_data:
            print("❌ No user data available for login test")
            return False

        login_data = {
            "username": self.user_data["email"],
            "password": self.user_data["password"]
        }
        
        success, response = self.run_test(
            "User Login",
            "POST",
            "login",
            200,
            data=login_data
        )
        
        if success and 'access_token' in response:
            self.token = response['access_token']
            return True
        return False

    def test_get_profile(self):
        """Test getting user profile"""
        success, response = self.run_test(
            "Get User Profile",
            "GET",
            "me",
            200
        )
        return success

    def test_get_subjects(self):
        """Test getting subjects list"""
        success, response = self.run_test(
            "Get Subjects",
            "GET",
            "subjects",
            200
        )
        if success:
            print(f"Found {len(response)} subjects")
        return success, response

    def test_attendance_flow(self):
        """Test complete attendance flow"""
        # First get subjects
        success, subjects = self.test_get_subjects()
        if not success or not subjects:
            print("❌ No subjects available for attendance test")
            return False

        # Record attendance for first subject
        subject_id = subjects[0]["id"]
        attendance_data = {
            "subject_id": subject_id,
            "date": datetime.utcnow().isoformat(),
            "status": "present"
        }

        success, response = self.run_test(
            "Record Attendance",
            "POST",
            "attendance",
            200,
            data=attendance_data
        )
        if not success:
            return False

        # Get attendance summary
        success, summary = self.run_test(
            "Get Attendance Summary",
            "GET",
            "attendance/summary",
            200
        )
        if success:
            print("Attendance Summary:", summary)
        return success

def main():
    # Setup
    base_url = "https://b5676da5-c4fb-4248-ac3b-bb2e570d8678.preview.emergentagent.com/api"
    tester = AttendanceAPITester(base_url)

    # Run tests
    if not tester.test_registration():
        print("❌ Registration failed, stopping tests")
        return 1

    if not tester.test_login():
        print("❌ Login failed, stopping tests")
        return 1

    if not tester.test_get_profile():
        print("❌ Profile retrieval failed")
        return 1

    if not tester.test_attendance_flow():
        print("❌ Attendance flow failed")
        return 1

    # Print results
    print(f"\n📊 Tests passed: {tester.tests_passed}/{tester.tests_run}")
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    main()