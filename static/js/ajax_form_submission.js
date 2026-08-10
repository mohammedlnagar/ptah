document.addEventListener("DOMContentLoaded", function () {
    
    // Function to submit appointment list form (CSV Upload)
    async function submitAppointmentListForm(event) {
        event.preventDefault();

        const form = document.getElementById("appointmentListForm");
        const formData = new FormData(form);
        formData.append("form_type", "appointments_list");

        const submitButton = document.getElementById("listSubmitButton");
        submitButton.disabled = true;
        submitButton.textContent = "Uploading...";

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
                headers: { "X-CSRFToken": getCSRFToken() },
            });

            const result = await response.json();
            alert(result.message);

            if (result.success) {
                form.reset();
            }
        } catch (error) {
            console.error("Error submitting form:", error);
            alert("An error occurred while submitting the form.");
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = "Create List";
        }
    }

    // Function to submit message template form
    async function submitMessageTemplateForm(event) {
        event.preventDefault();

        const form = document.getElementById("messageTemplateForm");
        const formData = new URLSearchParams(new FormData(form));
        formData.append("form_type", "message_template");

        const submitButton = document.getElementById("messageSubmitButton");
        submitButton.disabled = true;
        submitButton.textContent = "Saving...";

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": getCSRFToken(),
                },
            });

            const result = await response.json();
            alert(result.message);

            if (result.success) {
                form.reset();
            }
        } catch (error) {
            console.error("Error submitting form:", error);
            alert("An error occurred while submitting the form.");
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = "Save Message";
        }
    }

    // Function to get CSRF token from cookies
    function getCSRFToken() {
        return document.cookie.split("; ").find(row => row.startsWith("csrftoken="))?.split("=")[1] || "";
    }

    // Attach event listeners to forms
    document.getElementById("appointmentListForm").addEventListener("submit", submitAppointmentListForm);
    document.getElementById("messageTemplateForm").addEventListener("submit", submitMessageTemplateForm);
});
