document.addEventListener("DOMContentLoaded", () => {
    const app = document.getElementById("waiverApp");

    // =========================================================
    // CUSTOMER WAIVER
    // =========================================================

    if (app) {
        const steps = [...app.querySelectorAll(".step")];
        const peopleChoices = [...app.querySelectorAll("button[data-count]")];

        let currentStep = 1;

        let participantCount = 0;

        let nextParticipantId = 1;
        let participants = [];

        // ---------------------------------------------------------
        // Participants
        // ---------------------------------------------------------

        function createParticipant() {
            return {
                id: nextParticipantId++,
                firstName: "",
                lastName: "",
                age: "",
                gender: ""
            };
        }

        function ensureParticipantCount(count) {
            while (participants.length < count) {
                participants.push(createParticipant());
            }
        }

        ensureParticipantCount(participantCount);

        function hasParticipantData(person) {
            return Boolean(
                person.firstName.trim() ||
                person.lastName.trim() ||
                String(person.age).trim() ||
                person.gender.trim()
            );
        }

        function getParticipantName(person, index) {
            const name = `${person.firstName} ${person.lastName}`.trim();

            return name || `Person ${index + 1}`;
        }

        // ---------------------------------------------------------
        // Navigation
        // ---------------------------------------------------------

    function showStep(stepNumber) {
        currentStep = Math.max(1, Math.min(10, stepNumber));

        steps.forEach((step) => {
            step.classList.toggle(
                "active",
                Number(step.dataset.step) === currentStep
            );
        });

        if (currentStep === 3) {
            renderParticipants();
        }

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    }

    function buildWaiverData() {
    return {
        responsible_first_name:
            document.getElementById("responsibleFirstName")?.value.trim() || "",

        responsible_last_name:
            document.getElementById("responsibleLastName")?.value.trim() || "",

        responsible_email:
            document.getElementById("responsibleEmail")?.value.trim() || "",

        liability_acknowledged:
            document.getElementById("liability")?.checked || false,

        responsible_authority:
            document.getElementById("responsibleAuthority")?.checked || false,

        responsible_accuracy:
            document.getElementById("responsibleAccuracy")?.checked || false,

        signature_text:
            document.getElementById("waiverSignature")?.value.trim() || "",

        marketing_consent:
            document.getElementById("marketingConsent")?.checked || false,

        participants: participants.map((person) => ({
            first_name: person.firstName.trim(),
            last_name: person.lastName.trim(),
            age: Number(person.age),
            gender: person.gender
        }))
    };
}

        function populateWaiverSummary(waiverReference) {
    const summaryReference =
    document.getElementById("summaryReference");

    if (summaryReference) {
        summaryReference.textContent = waiverReference;
    }
    const firstName =
        document.getElementById("responsibleFirstName")?.value.trim() || "";

    const lastName =
        document.getElementById("responsibleLastName")?.value.trim() || "";

    const email =
        document.getElementById("responsibleEmail")?.value.trim() || "";

    const responsibleAdult =
        `${firstName} ${lastName}`.trim();

    const summaryResponsibleAdult =
        document.getElementById("summaryResponsibleAdult");

    const summaryEmail =
        document.getElementById("summaryEmail");

    const summaryPeopleCount =
        document.getElementById("summaryPeopleCount");

    const summaryParticipants =
        document.getElementById("summaryParticipants");

    const summaryCompletedDate =
        document.getElementById("summaryCompletedDate");

    const summaryExpiryDate =
        document.getElementById("summaryExpiryDate");

    if (summaryResponsibleAdult) {
        summaryResponsibleAdult.textContent =
            responsibleAdult || "—";
    }

    if (summaryEmail) {
        summaryEmail.textContent =
            email || "—";
    }

    if (summaryPeopleCount) {
        summaryPeopleCount.textContent =
            participantCount === 1
                ? "1 person"
                : `${participantCount} people`;
    }

    if (summaryParticipants) {
        summaryParticipants.innerHTML = "";

        participants.forEach((person, index) => {
            const row =
                document.createElement("div");

            row.className = "summary-row";

            row.innerHTML = `
                <span>Person ${index + 1}</span>
                <strong>
                    ${escapeHtml(
                        `${person.firstName} ${person.lastName}`.trim()
                    )}
                    — Age ${escapeHtml(person.age)}
                </strong>
            `;

            summaryParticipants.appendChild(row);
        });
    }

    const completedDate = new Date();

    const expiryDate = new Date(completedDate);

    expiryDate.setFullYear(
        expiryDate.getFullYear() + 1
    );

    const formatDate = (date) =>
        date.toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric"
        });

    if (summaryCompletedDate) {
        summaryCompletedDate.textContent =
            formatDate(completedDate);
    }

    if (summaryExpiryDate) {
        summaryExpiryDate.textContent =
            formatDate(expiryDate);
    }
}

        app.querySelectorAll(".next").forEach((button) => {
            button.addEventListener("click", async () => {
                const requiredId = button.dataset.requires;

                if (requiredId) {
                    const required =
                        document.getElementById(requiredId);

                    if (!required || !required.checked) {
                        alert(
                            "Please confirm this item before continuing."
                        );
                        return;
                    }
                }

        if (currentStep === 3) {
            if (participantCount < 1) {
                alert("Please select how many people need a waiver.");
                return;
            }

            const incompletePerson = participants.find((person) => {
                return (
                    !person.firstName.trim() ||
                    !person.lastName.trim() ||
                    !String(person.age).trim() ||
                    !person.gender.trim()
                );
            });

            if (incompletePerson) {
                alert(
                    "Please complete the first name, last name, age and gender for every person before continuing."
                );
                return;
            }

            const invalidAge = participants.find((person) => {
                const age = Number(person.age);
                return !Number.isFinite(age) || age < 2 || age > 120;
            });

            if (invalidAge) {
                alert("Please enter a valid age of 2 or above for every person.");
                return;
            }
        }

        if (currentStep === 3) {
            const firstName =
                document.getElementById("responsibleFirstName")?.value.trim();

            const lastName =
                document.getElementById("responsibleLastName")?.value.trim();

            const email =
                document.getElementById("responsibleEmail")?.value.trim();

            const authority =
                document.getElementById("responsibleAuthority")?.checked;

            const accuracy =
                document.getElementById("responsibleAccuracy")?.checked;

            if (!firstName || !lastName || !email) {
                alert(
                    "Please complete the responsible adult's first name, last name and email address before continuing."
                );
                return;
            }

            const signature =
                document.getElementById("waiverSignature")?.value.trim();

            if (!signature) {
                alert("Please provide your signature before submitting the waiver.");
                return;
            }

            const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

            if (!emailPattern.test(email)) {
                alert("Please enter a valid email address.");
                return;
            }

            if (!authority || !accuracy) {
                alert(
                    "Please confirm both Consent & Acknowledgement statements before continuing."
                );
                return;
            }
        }

                const currentIndex = steps.findIndex(
                    (step) => Number(step.dataset.step) === currentStep
                );

                const nextStep = steps[currentIndex + 1];

            if (
    currentStep === 3 &&
    Number(nextStep?.dataset.step) === 4
) {
    const waiverData = buildWaiverData();

    try {
        const eventId = document.getElementById("waiverApp")?.dataset.eventId;

        if (!eventId) {
            alert("The event could not be identified. Please use the waiver link provided for your event.");
            return;
        }

        const response = await fetch(`/api/waivers/event/${eventId}`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(waiverData)
        });

        const result = await response.json();

        if (!response.ok || !result.success) {
            alert(
                "There was a problem submitting the waiver. Please try again."
            );
            return;
        }

        console.log(
            "Waiver saved successfully:",
            result.waiver_reference
        );

        populateWaiverSummary(result.waiver_reference);

    } catch (error) {
        console.error("Waiver submission failed:", error);

        alert(
            "There was a problem submitting the waiver. Please try again."
        );

        return;
    }
}

                if (nextStep) {
                    showStep(Number(nextStep.dataset.step));
                }
            });
        });

        app.querySelectorAll(".back").forEach((button) => {
            button.addEventListener("click", () => {
                const currentIndex = steps.findIndex(
                    (step) => Number(step.dataset.step) === currentStep
                );

                const previousStep = steps[currentIndex - 1];

                if (previousStep) {
                    showStep(Number(previousStep.dataset.step));
                }
            });
        });

        // ---------------------------------------------------------
        // Step 5 - participant details
        // ---------------------------------------------------------

        const participantStep =
            app.querySelector('.step[data-step="3"]');

        const participantNavRow =
            participantStep?.querySelector(".nav");

        const participantPanels =
    document.getElementById("participantPanels");

        // Remove the fixed participant boxes from the original prototype.
        participantStep
            ?.querySelectorAll(".person-panel")
            .forEach((panel) => panel.remove());

        function escapeHtml(value) {
            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function createParticipantPanel(person, index) {
            const panel = document.createElement("div");

            panel.className = "person-panel";
            panel.dataset.participantId = person.id;

            panel.innerHTML = `
                <h2>Person ${index + 1}</h2>

                <label>
                    First name <span>*</span>
                    <input
                        type="text"
                        data-field="firstName"
                        value="${escapeHtml(person.firstName)}"
                        placeholder="First name"
                        autocomplete="given-name"
                    >
                </label>

                <label>
                    Last name <span>*</span>
                    <input
                        type="text"
                        data-field="lastName"
                        value="${escapeHtml(person.lastName)}"
                        placeholder="Last name"
                        autocomplete="family-name"
                    >
                </label>

                <label>
                    Age <span>*</span>
                    <input
                        type="number"
                        data-field="age"
                        value="${escapeHtml(person.age)}"
                        min="2"
                        max="120"
                        placeholder="Age"
                    >
                </label>

                <label>
                    Gender <span>*</span>
                    <select data-field="gender">
                        <option value="">Please select</option>
                        <option value="Male">Male</option>
                        <option value="Female">Female</option>
                        <option value="Gender Neutral">
                            Gender Neutral
                        </option>
                    </select>
                </label>
            `;

            const gender =
                panel.querySelector('[data-field="gender"]');

            gender.value = person.gender;

            panel
                .querySelectorAll("[data-field]")
                .forEach((field) => {
                    function save() {
                        person[field.dataset.field] = field.value;
                    }

                    field.addEventListener("input", save);
                    field.addEventListener("change", save);
                });

            return panel;
        }

        function renderParticipants() {
            if (!participantStep || !participantPanels) {
                return;
            }

            participantStep
                .querySelectorAll(".person-panel")
                .forEach((panel) => panel.remove());

            participants.forEach((person, index) => {
                const panel =
                    createParticipantPanel(person, index);

                participantPanels.appendChild(panel);
                            });

            const note =
                participantStep.querySelector(".small-note");

            if (note) {
                if (participantCount === 1) {
                    note.textContent =
                        "Please enter the details of the person being painted.";
                } else {
                    note.textContent =
                        `Please enter the details of all ${participantCount} people being painted.`;
                }
            }
        }

        // ---------------------------------------------------------
        // Step 2 - number of people
        // ---------------------------------------------------------

        function updatePeopleButtons() {
            peopleChoices.forEach((button) => {
                button.classList.toggle(
                    "selected",
                    Number(button.dataset.count) ===
                        participantCount
                );
            });
        }

        peopleChoices.forEach((button) => {
            button.addEventListener("click", () => {
                const requested =
                    Number(button.dataset.count);

                if (requested === participantCount) {
                    return;
                }

                if (requested > participantCount) {
                    increasePeople(requested);
                } else {
                    reducePeople(requested);
                }
            });
        });

        function increasePeople(newCount) {
            ensureParticipantCount(newCount);

            participantCount = newCount;

            updatePeopleButtons();
            renderParticipants();
        }

        function reducePeople(newCount) {
            const amountToRemove =
                participantCount - newCount;

            const blankPeople =
                participants.filter(
                    (person) => !hasParticipantData(person)
                );

            /*
             * If enough completely empty participant boxes exist,
             * remove those automatically.
             */
            if (blankPeople.length >= amountToRemove) {
                const ids = blankPeople
                    .slice(-amountToRemove)
                    .map((person) => person.id);

                participants =
                    participants.filter(
                        (person) =>
                            !ids.includes(person.id)
                    );

                participantCount = newCount;

                updatePeopleButtons();
                renderParticipants();

                return;
            }

            /*
             * Empty records can safely be removed.
             * Populated records must be chosen by the customer.
             */
            const blankIds =
                blankPeople.map((person) => person.id);

            const populatedPeople =
                participants.filter(
                    (person) =>
                        !blankIds.includes(person.id)
                );

            const populatedToRemove =
                amountToRemove - blankIds.length;

            showRemovalModal(
                populatedPeople,
                populatedToRemove
            ).then((chosenIds) => {
                if (chosenIds === null) {
                    // Customer cancelled.
                    updatePeopleButtons();
                    return;
                }

                const allIdsToRemove = [
                    ...blankIds,
                    ...chosenIds
                ];

                participants =
                    participants.filter(
                        (person) =>
                            !allIdsToRemove.includes(
                                person.id
                            )
                    );

                participantCount = newCount;

                updatePeopleButtons();
                renderParticipants();
            });
        }

        // ---------------------------------------------------------
        // Remove participant modal
        // ---------------------------------------------------------

        function showRemovalModal(
            availablePeople,
            requiredAmount
        ) {
            return new Promise((resolve) => {
                const overlay =
                    document.createElement("div");

                overlay.className =
                    "participant-modal-overlay";

                const modal =
                    document.createElement("div");

                modal.className =
                    "participant-modal";

                const title =
                    requiredAmount === 1
                        ? "Which person would you like to remove?"
                        : `Which ${requiredAmount} people would you like to remove?`;

                modal.innerHTML = `
                    <h2>${title}</h2>

                    <p>
                        You've already entered information for these
                        people, so we won't delete it automatically.
                    </p>

                    <div class="participant-removal-list"></div>

                    <div class="participant-modal-count">
                        Select exactly
                        <strong>${requiredAmount}</strong>
                        ${
                            requiredAmount === 1
                                ? "person"
                                : "people"
                        }.
                    </div>

                    <div class="participant-modal-actions">
                        <button
                            type="button"
                            class="button secondary modal-cancel"
                        >
                            Cancel
                        </button>

                        <button
                            type="button"
                            class="button primary modal-confirm"
                            disabled
                        >
                            Remove Selected
                        </button>
                    </div>
                `;

                overlay.appendChild(modal);
                document.body.appendChild(overlay);

                const list =
                    modal.querySelector(
                        ".participant-removal-list"
                    );

                const confirmButton =
                    modal.querySelector(
                        ".modal-confirm"
                    );

                const cancelButton =
                    modal.querySelector(
                        ".modal-cancel"
                    );

                availablePeople.forEach(
                    (person, index) => {
                        const option =
                            document.createElement(
                                "label"
                            );

                        option.className =
                            "participant-removal-option";

                        option.innerHTML = `
                            <input
                                type="checkbox"
                                value="${person.id}"
                            >

                            <span>
                                <strong>
                                    ${escapeHtml(
                                        getParticipantName(
                                            person,
                                            index
                                        )
                                    )}
                                </strong>

                                <small>
                                    Person ${index + 1}
                                    ${
                                        person.age
                                            ? ` • Age ${escapeHtml(
                                                  person.age
                                              )}`
                                            : ""
                                    }
                                </small>
                            </span>
                        `;

                        list.appendChild(option);
                    }
                );

                const checkboxes = [
                    ...list.querySelectorAll(
                        'input[type="checkbox"]'
                    )
                ];

                function updateSelection() {
                    const selected =
                        checkboxes.filter(
                            (box) => box.checked
                        );

                    confirmButton.disabled =
                        selected.length !==
                        requiredAmount;

                    checkboxes.forEach((box) => {
                        if (
                            !box.checked &&
                            selected.length >=
                                requiredAmount
                        ) {
                            box.disabled = true;
                        } else {
                            box.disabled = false;
                        }
                    });
                }

                checkboxes.forEach((box) => {
                    box.addEventListener(
                        "change",
                        updateSelection
                    );
                });

                cancelButton.addEventListener(
                    "click",
                    () => {
                        overlay.remove();
                        resolve(null);
                    }
                );

                confirmButton.addEventListener(
                    "click",
                    () => {
                        const selectedIds =
                            checkboxes
                                .filter(
                                    (box) =>
                                        box.checked
                                )
                                .map((box) =>
                                    Number(box.value)
                                );

                        if (
                            selectedIds.length !==
                            requiredAmount
                        ) {
                            return;
                        }

                        overlay.remove();

                        resolve(selectedIds);
                    }
                );
            });
        }

        // ---------------------------------------------------------
        // Modal appearance
        // ---------------------------------------------------------

        const style =
            document.createElement("style");

        style.textContent = `
            .participant-modal-overlay {
                position: fixed;
                inset: 0;
                z-index: 9999;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                background: rgba(10, 23, 48, 0.72);
            }

            .participant-modal {
                width: min(100%, 480px);
                max-height: 90vh;
                overflow-y: auto;
                padding: 22px;
                background: white;
                border-radius: 20px;
                box-shadow:
                    0 24px 70px rgba(0, 0, 0, 0.28);
            }

            .participant-modal h2 {
                margin-top: 0;
                color: #12213d;
            }

            .participant-modal p {
                color: #667189;
                line-height: 1.5;
            }

            .participant-removal-list {
                display: grid;
                gap: 10px;
                margin-top: 18px;
            }

            .participant-removal-option {
                display: flex !important;
                align-items: center;
                gap: 12px;
                margin: 0 !important;
                padding: 13px;
                border: 1px solid #e1e6ef;
                border-radius: 14px;
                background: #fbfcff;
                cursor: pointer;
            }

            .participant-removal-option:hover {
                border-color: #f52f83;
                background: #fff0f6;
            }

            .participant-removal-option input {
                width: 21px;
                height: 21px;
                margin: 0;
                flex-shrink: 0;
                accent-color: #f52f83;
            }

            .participant-removal-option span {
                display: flex;
                flex-direction: column;
                gap: 3px;
            }

            .participant-removal-option small {
                color: #667189;
            }

            .participant-modal-count {
                margin: 18px 0;
                padding: 12px;
                border-radius: 12px;
                background: #fff0f6;
                color: #667189;
                text-align: center;
            }

            .participant-modal-actions {
                display: flex;
                justify-content: flex-end;
                gap: 10px;
            }

            @media (max-width: 520px) {
                .participant-modal-actions {
                    flex-direction: column-reverse;
                }

                .participant-modal-actions .button {
                    width: 100%;
                }
            }
        `;

        document.head.appendChild(style);

        updatePeopleButtons();
        renderParticipants();
        showStep(1);
    }

    // =========================================================
    // ADMIN EVENT STATUS
    // =========================================================

    const stateButtons = [
        ...document.querySelectorAll(".state")
    ];

    const stateMessage =
        document.getElementById("stateMessage");

    if (stateButtons.length && stateMessage) {
        const messages = {
            Open:
                "New waivers can be submitted.",

            "Closing Soon":
                "Customers can still submit, but will see a warning that face painting is nearing the end.",

            Closed:
                "New waiver submissions are unavailable."
        };

        stateButtons.forEach((button) => {
            button.addEventListener("click", () => {
                stateButtons.forEach((item) => {
                    item.classList.remove("active");
                });

                button.classList.add("active");

                stateMessage.textContent =
                    messages[
                        button.dataset.state
                    ] || "";
            });
        });
    }
});