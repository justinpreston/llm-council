import { useState, useEffect } from 'react';
import './Settings.css';

const STORAGE_KEY = 'llm-council-settings';

const defaultSettings = {
  customInstructions: '',
  quickMode: false,
  lightMode: false,
};

export function loadSettings() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return { ...defaultSettings, ...JSON.parse(stored) };
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
  return defaultSettings;
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch (e) {
    console.error('Failed to save settings:', e);
  }
}

export default function Settings({ isOpen, onClose, settings, onSave }) {
  const [customInstructions, setCustomInstructions] = useState('');
  const [quickMode, setQuickMode] = useState(false);
  const [lightMode, setLightMode] = useState(false);

  useEffect(() => {
    if (isOpen && settings) {
      setCustomInstructions(settings.customInstructions || '');
      setQuickMode(settings.quickMode || false);
      setLightMode(settings.lightMode || false);
    }
  }, [isOpen, settings]);

  const handleSave = () => {
    const newSettings = {
      customInstructions,
      quickMode,
      lightMode,
    };
    saveSettings(newSettings);
    onSave(newSettings);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="settings-content">
          <div className="settings-section">
            <h3>Custom Instructions</h3>
            <p className="settings-description">
              These instructions will be included in every prompt to guide how the council responds.
              For example: "Always respond in a formal academic tone" or "Focus on practical examples".
            </p>
            <textarea
              className="custom-instructions-input"
              value={customInstructions}
              onChange={(e) => setCustomInstructions(e.target.value)}
              placeholder="Enter custom instructions for the council..."
              rows={6}
            />
          </div>

          <div className="settings-section">
            <h3>Response Mode</h3>
            <p className="settings-description">
              Choose how the council processes your queries.
            </p>
            
            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={lightMode}
                onChange={(e) => {
                  setLightMode(e.target.checked);
                  if (e.target.checked) setQuickMode(false); // Light mode implies quick mode
                }}
              />
              <span className="checkbox-label">
                <strong>Light Mode</strong> — Use faster, cheaper models (Gemini Flash, Grok, DeepSeek)
              </span>
            </label>

            <label className="settings-checkbox">
              <input
                type="checkbox"
                checked={quickMode}
                disabled={lightMode}
                onChange={(e) => setQuickMode(e.target.checked)}
              />
              <span className="checkbox-label">
                <strong>Quick Mode</strong> — Skip peer ranking (Stage 2) for faster responses
              </span>
            </label>
          </div>
        </div>

        <div className="settings-footer">
          <button className="cancel-btn" onClick={onClose}>Cancel</button>
          <button className="save-btn" onClick={handleSave}>Save Settings</button>
        </div>
      </div>
    </div>
  );
}
