"""Greeting-name extraction for rendered messages."""

from django.test import SimpleTestCase

from messaging.formatting import first_name


class FirstNameTests(SimpleTestCase):
    def assert_first_name(self, full_name, expected):
        self.assertEqual(first_name(full_name), expected)

    def test_a_plain_name_keeps_its_first_word(self):
        self.assert_first_name("Ahmed Ali", "Ahmed")

    def test_a_single_word_name_is_returned_whole(self):
        self.assert_first_name("Ahmed", "Ahmed")

    def test_titles_are_dropped(self):
        self.assert_first_name("Mr. Ahmed Ali", "Ahmed")
        self.assert_first_name("Mr Ahmed Ali", "Ahmed")
        self.assert_first_name("Ms. Sara Khalid", "Sara")
        self.assert_first_name("Ms Sara Khalid", "Sara")
        self.assert_first_name("Dr Yousef Hassan", "Yousef")

    def test_stacked_titles_are_dropped(self):
        self.assert_first_name("Mr. Dr. Ahmed Ali", "Ahmed")

    def test_a_particle_keeps_the_word_after_it(self):
        self.assert_first_name("Al Mansoori Ahmed", "Al Mansoori")
        self.assert_first_name("El Sayed Mohamed", "El Sayed")
        self.assert_first_name("Abdul Rahman Ahmed", "Abdul Rahman")

    def test_a_title_before_a_particle(self):
        self.assert_first_name("MR. AHMED AL MANSOORI", "Ahmed")
        self.assert_first_name("Mr Al Mansoori Ahmed", "Al Mansoori")

    def test_a_trailing_particle_has_nothing_to_join(self):
        self.assert_first_name("Al", "Al")

    def test_all_caps_is_tidied(self):
        self.assert_first_name("AHMED ALI", "Ahmed")

    def test_all_lowercase_is_tidied(self):
        self.assert_first_name("ahmed ali", "Ahmed")

    def test_mixed_case_is_left_alone(self):
        # Deliberately not title-cased: McDonald is spelled that way on purpose.
        self.assert_first_name("McDonald Smith", "McDonald")

    def test_a_hyphenated_name_stays_one_token(self):
        self.assert_first_name("AL-AHMED SALEH", "Al-Ahmed")

    def test_an_apostrophe_name_is_tidied(self):
        self.assert_first_name("O'BRIEN PATRICK", "O'Brien")

    def test_extra_whitespace_is_collapsed(self):
        self.assert_first_name("   Ahmed    Ali  ", "Ahmed")

    def test_an_arabic_name_survives_untouched(self):
        # Arabic is caseless, so title stripping and case tidying must no-op
        # rather than reject the name.
        self.assert_first_name("محمد علي", "محمد")

    def test_a_title_only_string_falls_back_to_the_title(self):
        # Nothing else to greet with; better than returning an empty string.
        self.assert_first_name("Mr.", "Mr.")

    def test_empty_input_returns_empty(self):
        self.assert_first_name("", "")
        self.assert_first_name("   ", "")
        self.assert_first_name(None, "")
