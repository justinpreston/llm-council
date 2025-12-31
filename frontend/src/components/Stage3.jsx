import ReactMarkdown from 'react-markdown';
import './Stage3.css';

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

export default function Stage3({ finalResponse }) {
  if (!finalResponse) {
    return null;
  }

  return (
    <div className="stage stage3">
      <div className="stage-header">
        <h3 className="stage-title">Stage 3: Final Council Answer</h3>
        {finalResponse.usage?.total_tokens > 0 && (
          <div className="stage-tokens">
            {finalResponse.usage.total_tokens.toLocaleString()} tokens
          </div>
        )}
      </div>
      <div className="final-response">
        <div className="model-header">
          <div className="chairman-label">
            Chairman: {finalResponse.model.split('/')[1] || finalResponse.model}
          </div>
          <TokenUsage usage={finalResponse.usage} />
        </div>
        <div className="final-text markdown-content">
          <ReactMarkdown>{finalResponse.response}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
