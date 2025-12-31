import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage1.css';

function TokenUsage({ usage }) {
  if (!usage || !usage.total_tokens) return null;
  
  return (
    <div className="token-usage">
      <span className="token-label">Tokens:</span>
      <span className="token-value">{usage.prompt_tokens?.toLocaleString() || 0} in</span>
      <span className="token-separator">→</span>
      <span className="token-value">{usage.completion_tokens?.toLocaleString() || 0} out</span>
      <span className="token-total">({usage.total_tokens?.toLocaleString() || 0} total)</span>
    </div>
  );
}

export default function Stage1({ responses }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!responses || responses.length === 0) {
    return null;
  }

  // Calculate totals
  const totalTokens = responses.reduce((sum, r) => sum + (r.usage?.total_tokens || 0), 0);

  return (
    <div className="stage stage1">
      <div className="stage-header">
        <h3 className="stage-title">Stage 1: Individual Responses</h3>
        {totalTokens > 0 && (
          <div className="stage-tokens">
            Total: {totalTokens.toLocaleString()} tokens
          </div>
        )}
      </div>

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {resp.model.split('/')[1] || resp.model}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="model-header">
          <div className="model-name">{responses[activeTab].model}</div>
          <TokenUsage usage={responses[activeTab].usage} />
        </div>
        <div className="response-text markdown-content">
          <ReactMarkdown>{responses[activeTab].response}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
