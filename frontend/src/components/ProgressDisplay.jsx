const ProgressDisplay = ({ progress }) => {
  if (!progress || !progress.message) {
    return null
  }

  return (
    <div className="mt-8 max-w-2xl mx-auto">
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="flex items-center mb-4">
          <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span className="text-blue-600 font-medium text-lg">Processing...</span>
        </div>
        
        {/* Progress Message */}
        <div className="mb-4">
          <p className="text-gray-700 text-sm">{progress.message}</p>
        </div>
        
        {/* Progress Bar */}
        {progress.total > 0 && (
          <div className="mb-4">
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm text-gray-600">
                Step {progress.step} of {progress.total}
              </span>
              <span className="text-sm text-gray-600">
                {progress.progress}%
              </span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div 
                className="bg-blue-600 h-2 rounded-full transition-all duration-300 ease-in-out"
                style={{ width: `${progress.progress}%` }}
              ></div>
            </div>
          </div>
        )}
        
        {/* Step Indicator */}
        {progress.total > 0 && (
          <div className="flex items-center justify-center space-x-2">
            {Array.from({ length: progress.total }, (_, i) => (
              <div
                key={i}
                className={`w-3 h-3 rounded-full ${
                  i < progress.step
                    ? 'bg-green-500'
                    : i === progress.step - 1
                    ? 'bg-blue-500'
                    : 'bg-gray-300'
                }`}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ProgressDisplay