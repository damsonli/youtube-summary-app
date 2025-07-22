import { useState } from 'react'
import VideoAnalyzer from './components/VideoAnalyzer'
import VideoResults from './components/VideoResults'
import ProgressDisplay from './components/ProgressDisplay'
import SubscriptionManager from './components/SubscriptionManager'
import LLMServiceStatus from './components/LLMServiceStatus'

function App() {
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState({ message: '', step: 0, total: 0, progress: 0 })
  const [activeTab, setActiveTab] = useState('analyze')

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <header className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-800 mb-2">
            YouTube Video Analyzer
          </h1>
          <p className="text-gray-600">
            Get AI-powered summaries of YouTube videos and channels
          </p>
        </header>

        {/* Tab Navigation */}
        <div className="max-w-4xl mx-auto mb-8">
          <div className="flex space-x-1 bg-gray-100 p-1 rounded-lg">
            <button
              onClick={() => setActiveTab('analyze')}
              className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'analyze'
                  ? 'bg-white text-blue-600 shadow'
                  : 'text-gray-600 hover:text-gray-800'
              }`}
            >
              Analyze Videos
            </button>
            <button
              onClick={() => setActiveTab('subscriptions')}
              className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                activeTab === 'subscriptions'
                  ? 'bg-white text-blue-600 shadow'
                  : 'text-gray-600 hover:text-gray-800'
              }`}
            >
              Subscriptions
            </button>
          </div>
        </div>

        <div className="max-w-4xl mx-auto">
          {activeTab === 'analyze' && (
            <>
              <LLMServiceStatus />
              
              <VideoAnalyzer 
                onResults={setResults}
                onLoading={setLoading}
                onProgress={setProgress}
              />
              
              {loading && (
                <ProgressDisplay progress={progress} />
              )}

              {results.length > 0 && (
                <VideoResults results={results} />
              )}
            </>
          )}

          {activeTab === 'subscriptions' && (
            <SubscriptionManager />
          )}
        </div>
      </div>
    </div>
  )
}

export default App