/**
 * Smart Matcher Utility Functions
 * Reusable functions for file pairing functionality
 */

function initializeSmartMatcher(formId, addPairBtnId, containerId, pairCountId, isSplitView = false) {
    const matchingForm = document.getElementById(formId);
    const addPairBtn = document.getElementById(addPairBtnId);
    const filePairsContainer = document.getElementById(containerId);

    if (!matchingForm || !addPairBtn || !filePairsContainer) {
        return;
    }
    
    const isLoggedIn = document.body.dataset.userId !== '';

    const modeFileRadio = document.getElementById('match_mode_file');
    const modeBatchRadio = document.getElementById('match_mode_batch');
    const batchSelectWrapper = document.querySelector('.batch-select-wrapper');
    const batchSelect = document.getElementById('batch_id');

    // Function to update file name display
    function updateFileNameDisplay(inputElement, displayElementId) {
        const fileName = inputElement.files[0] ? inputElement.files[0].name : '';
        const displayElement = document.getElementById(displayElementId);
        if (displayElement) {
            displayElement.textContent = fileName ? `Selected: ${fileName}` : '';
        }
    }

    function updateModeUI() {
        const usingBatch = modeBatchRadio && modeBatchRadio.checked;
        // Handle both class names for compatibility (standalone page uses master-mode-wrapper, split view uses master-file-wrapper)
        const masterWrappers = filePairsContainer.querySelectorAll('.master-mode-wrapper, .master-file-wrapper');
        const masterInputs = filePairsContainer.querySelectorAll('.master-input');

        masterWrappers.forEach(w => {
            if (usingBatch) {
                w.classList.add('d-none');
            } else {
                w.classList.remove('d-none');
            }
        });
        masterInputs.forEach(inp => {
            if (usingBatch) {
                inp.removeAttribute('required');
            } else {
                inp.setAttribute('required', 'required');
            }
        });

        if (batchSelectWrapper) {
            if (usingBatch) {
                batchSelectWrapper.classList.remove('d-none');
            } else {
                batchSelectWrapper.classList.add('d-none');
                if (batchSelect) batchSelect.value = '';
            }
        }
    }

    // Add event listeners for batch mode radios
    if (modeFileRadio) {
        modeFileRadio.addEventListener('change', updateModeUI);
    }
    if (modeBatchRadio) {
        modeBatchRadio.addEventListener('change', updateModeUI);
    }
    
    // Initialize mode UI on page load
    updateModeUI();

    // Add event listeners to initial file inputs

    const initialMasterInput = filePairsContainer.querySelector('input[name="master_file_0"]');
    const initialRawInput = filePairsContainer.querySelector('input[name="raw_file_0"]');
    
    if (initialMasterInput) {
        initialMasterInput.addEventListener('change', function() {
            updateFileNameDisplay(this, 'master_file_name_0');
        });

    }
    
    if (initialRawInput) {
        initialRawInput.addEventListener('change', function() {
            updateFileNameDisplay(this, 'raw_file_name_0');
        });
    }
    
    // Form submission behavior

    if (matchingForm) {
        matchingForm.addEventListener('submit', function(e) {
            console.log('[Smart Matcher] Form submit triggered');
            
            if (!isLoggedIn) {
                // Redirect anonymous users to login without processing
                e.preventDefault();
                window.location.href = '/login';
                return;
            }

            // Clear previous error highlighting
            filePairsContainer.querySelectorAll('.file-pair-row').forEach(row => {
                row.classList.remove('border-danger');
                row.classList.remove('border-2');
            });

            // Get all file pair rows
            const allRows = filePairsContainer.querySelectorAll('.file-pair-row');
            let firstErrorMessage = '';
            let hasError = false;
            let pairNum = 0;

            console.log('[Smart Matcher] Validating ' + allRows.length + ' pairs');

            allRows.forEach((row, index) => {
                pairNum++;
                const rawInput = row.querySelector('.raw-input');
                const sourceSelect = row.querySelector('.master-source-select');
                const batchSelect = row.querySelector('.master-batch-wrapper select');
                const masterInput = row.querySelector('.master-input');
                
                const isPairBatchMode = sourceSelect && sourceSelect.value === 'batch';
                
                console.log('[Smart Matcher] Pair ' + pairNum + ': batchMode=' + isPairBatchMode + 
                    ', batchValue=' + (batchSelect ? batchSelect.value : 'N/A') +
                    ', rawFile=' + (rawInput && rawInput.files && rawInput.files.length > 0 ? 'YES' : 'NO'));
                
                // Check raw file - always required
                if (!rawInput || !rawInput.files || rawInput.files.length === 0) {
                    hasError = true;
                    if (!firstErrorMessage) {
                        firstErrorMessage = `Pair #${pairNum}: Please select a raw file.`;
                    }
                    row.classList.add('border-danger', 'border-2');
                    return;
                }
                
                if (isPairBatchMode) {
                    // Batch mode: only need batch selection + raw file
                    if (!batchSelect || !batchSelect.value) {
                        hasError = true;
                        if (!firstErrorMessage) {
                            firstErrorMessage = `Pair #${pairNum}: Please select a batch.`;
                        }
                        row.classList.add('border-danger', 'border-2');
                    }
                    // Master file NOT required in batch mode
                } else {
                    // File mode: need master file + raw file
                    if (!masterInput || !masterInput.files || masterInput.files.length === 0) {
                        hasError = true;
                        if (!firstErrorMessage) {
                            firstErrorMessage = `Pair #${pairNum}: Please select a master file.`;
                        }
                        row.classList.add('border-danger', 'border-2');
                    }
                }
            });

            if (hasError) {
                console.log('[Smart Matcher] Validation failed: ' + firstErrorMessage);
                e.preventDefault();
                if (firstErrorMessage) {
                    alert(firstErrorMessage);
                }
            } else {
                console.log('[Smart Matcher] Validation passed, submitting form...');
                // Let the form submit naturally
            }
        });
    }
    
    // Add pair button functionality
    // Check if batch selection is available (superadmin or batch matching enabled)
    // Wait a tick to ensure the DOM is ready with the batch selector from initializeBatchSelection
    let hasBatchOption = false;
    let batchOptionsHtml = '';
    
    // Function to refresh batch options - called after a short delay to ensure DOM is ready
    function refreshBatchOptions() {
        hasBatchOption = document.querySelector('.master-source-select') !== null;
        const batchSelect = document.querySelector('[name="batch_id_0"]');
        batchOptionsHtml = (hasBatchOption && batchSelect) ? batchSelect.innerHTML : '';
        console.log('[Smart Matcher] Batch options refreshed: hasBatchOption=' + hasBatchOption + ', options=' + (batchOptionsHtml ? 'found' : 'empty'));
    }
    
    // Initial refresh after a short delay
    setTimeout(refreshBatchOptions, 100);

    addPairBtn.addEventListener('click', function() {
        // Refresh batch options before adding pair
        refreshBatchOptions();
        
        const pairCountInput = document.getElementById(pairCountId);
        let pairIndex = parseInt(pairCountInput.value);
        const newPair = document.createElement('div');

        newPair.className = 'file-pair-row card border mb-1';
        newPair.setAttribute('data-pair-index', pairIndex);
        newPair.setAttribute('data-status', 'incomplete');
        newPair.style.borderRadius = '6px';
        
        let masterSourceHtml = '';
        let batchSelectHtml = '';
        let rawSpacerHtml = '';
        
        if (hasBatchOption) {
            masterSourceHtml = `
                <select class="form-select form-select-sm master-source-select mb-1" name="master_source_${pairIndex}" onchange="toggleMasterInput(${pairIndex}, this.value)" style="font-size: 0.65rem; padding: 2px 4px; height: 24px;">
                    <option value="file">Upload File</option>
                    <option value="batch" selected>Use Batch</option>
                </select>
            `;
            batchSelectHtml = `
                <div class="master-batch-wrapper" id="master-batch-wrapper-${pairIndex}" style="display: block;">
                    <select class="form-select form-select-sm" name="batch_id_${pairIndex}" style="font-size: 0.65rem; padding: 2px 4px; height: 26px;" onchange="updatePairStatus(${pairIndex});">
                        ${batchOptionsHtml}
                    </select>
                </div>
            `;
            rawSpacerHtml = '<div style="height: 24px;"></div>';
        }
        
        // If batch option exists, default to batch mode (hide file input completely)
        const fileWrapperStyle = hasBatchOption ? 'display: none;' : 'display: block;';
        const fileWrapperClass = hasBatchOption ? 'master-file-wrapper d-none' : 'master-file-wrapper';
        // Disable the master input if batch mode to prevent browser validation errors
        const masterInputDisabled = hasBatchOption ? 'disabled' : '';
        
        newPair.innerHTML = `
            <div class="card-header pair-header py-1 px-2 d-flex align-items-center justify-content-between" style="cursor: pointer; min-height: 28px;" onclick="togglePairCollapse(this);">
                <div class="d-flex align-items-center gap-1">
                    <span class="badge bg-primary rounded-pill" style="font-size: 0.6rem; padding: 2px 6px;">${pairIndex + 1}</span>
                    <span class="fw-semibold pair-title" style="font-size: 0.7rem;">Pair</span>
                    <span class="pair-status-text text-muted" style="font-size: 0.65rem;"></span>
                </div>
                <div class="d-flex align-items-center gap-1">
                    <span class="pair-status-icon"></span>
                    <button type="button" class="btn btn-sm btn-outline-danger remove-pair-btn py-0 px-1" style="font-size: 0.6rem;">
                        <i class="fas fa-times"></i>
                    </button>
                    <i class="fas fa-chevron-up collapse-icon text-muted" style="font-size: 0.6rem;"></i>
                </div>
            </div>
            <div class="card-body p-1 pair-body">
                <div class="d-flex gap-2">
                    <div style="flex: 1; min-width: 0;">
                        <label class="form-label mb-0" style="font-size: 0.65rem; font-weight: 600;">
                            <i class="fas fa-file-alt text-primary me-1"></i>Master
                        </label>
                        ${masterSourceHtml}
                        <div class="${fileWrapperClass}" id="master-file-wrapper-${pairIndex}" style="${fileWrapperStyle}">
                            <input class="form-control form-control-sm master-input" type="file" name="master_file_${pairIndex}" accept=".csv,.xlsx" style="font-size: 0.65rem; padding: 2px 4px; height: 26px;" ${masterInputDisabled} onchange="updatePairStatus(${pairIndex});">
                        </div>
                        ${batchSelectHtml}
                    </div>
                    <div style="flex: 1; min-width: 0;">
                        <label class="form-label mb-0" style="font-size: 0.65rem; font-weight: 600;">
                            <i class="fas fa-file-import text-success me-1"></i>Raw
                        </label>
                        ${rawSpacerHtml}
                        <input class="form-control form-control-sm raw-input" type="file" name="raw_file_${pairIndex}" accept=".csv,.xlsx" required style="font-size: 0.65rem; padding: 2px 4px; height: 26px;" ${!isLoggedIn ? 'disabled' : ''} onchange="updatePairStatus(${pairIndex});">
                    </div>
                </div>
            </div>
        `;
        filePairsContainer.appendChild(newPair);
        // Update pair count to match actual number of rows
        pairCountInput.value = filePairsContainer.querySelectorAll('.file-pair-row').length;
        console.log('[Smart Matcher] Added pair, total pairs: ' + pairCountInput.value);
        
        // Add event listeners to the new file inputs

        const newMasterInput = newPair.querySelector(`input[name="master_file_${pairIndex}"]`);
        const newRawInput = newPair.querySelector(`input[name="raw_file_${pairIndex}"]`);
        
        if (newMasterInput) {
            newMasterInput.addEventListener('change', function() {
                updateFileNameDisplay(this, `master_file_name_${pairIndex}`);
            });
        }
        
        if (newRawInput) {
            newRawInput.addEventListener('change', function() {
                updateFileNameDisplay(this, `raw_file_name_${pairIndex}`);
            });
        }

        // Apply current mode visibility to new row
        updateModeUI();
        
        // Enable remove button for first pair
        const firstRemoveBtn = filePairsContainer.querySelector('.remove-pair-btn');
        if (firstRemoveBtn) {
            firstRemoveBtn.disabled = false;
        }
    });
    
    // Remove pair functionality
    filePairsContainer.addEventListener('click', function(e) {
        if (e.target.closest('.remove-pair-btn')) {
            const row = e.target.closest('.file-pair-row');
            if (filePairsContainer.children.length > 1) {
                row.remove();
                // Update pair_count to reflect current number of pairs
                document.getElementById(pairCountId).value = filePairsContainer.children.length;
                
                // Update pair numbers for remaining pairs
                const pairs = filePairsContainer.querySelectorAll('.file-pair-row');
                pairs.forEach((pair, index) => {
                    const heading = pair.querySelector('h6');
                    if (heading) {
                        heading.textContent = `File Pair #${index + 1}`;
                    }
                    pair.setAttribute('data-pair-index', index);
                    
                    // Update input names
                    const masterInput = pair.querySelector('[name^="master_file"]');
                    const rawInput = pair.querySelector('[name^="raw_file"]');
                    if (masterInput) masterInput.name = `master_file_${index}`;
                    if (rawInput) rawInput.name = `raw_file_${index}`;
                    
                    // Update file name display IDs
                    const masterFileNameDisplay = pair.querySelector('[id^="master_file_name"]');
                    const rawFileNameDisplay = pair.querySelector('[id^="raw_file_name"]');
                    if (masterFileNameDisplay) masterFileNameDisplay.id = `master_file_name_${index}`;
                    if (rawFileNameDisplay) rawFileNameDisplay.id = `raw_file_name_${index}`;
                });
                
                // Disable remove button for first pair if only one pair left
                if (filePairsContainer.children.length === 1) {
                    const firstRemoveBtn = filePairsContainer.querySelector('.remove-pair-btn');
                    if (firstRemoveBtn) {
                        firstRemoveBtn.disabled = true;
                    }
                }
            }
        }
    });
    
    // Allow normal form submission for file downloads when validation passes
}