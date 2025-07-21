import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const VideoResults = ({ results }) => {
  if (!results || results.length === 0) {
    return (
      <div className="mt-8 max-w-2xl mx-auto">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
          <div className="text-yellow-600 mb-2">
            <svg className="mx-auto h-12 w-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.268 15.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-yellow-800 mb-1">No videos found</h3>
          <p className="text-yellow-600">
            No videos were found matching your criteria. Try adjusting your date filter or increasing the video limit.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-8 space-y-6">
      <h2 className="text-2xl font-bold text-gray-800">Analysis Results</h2>
      
      <div className="grid gap-6">
        {results.map((video, index) => (
          <div key={index} className="bg-white rounded-lg shadow-md overflow-hidden">
            <div className="md:flex">
              {/* Thumbnail */}
              <div className="md:w-1/3">
                <div className="relative w-full aspect-video">
                  <img
                    src={video.thumbnail}
                    alt={video.title}
                    className="w-full h-full object-cover rounded-md"
                  />
                </div>
              </div>
              
              {/* Content */}
              <div className="md:w-2/3 p-6">
                <div className="flex items-start justify-between">
                  <h3 className="text-xl font-semibold text-gray-800 mb-2">
                    <a 
                      href={video.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:text-blue-600 transition-colors"
                    >
                      {video.title}
                    </a>
                  </h3>
                  <span className="bg-gray-100 text-gray-600 px-2 py-1 rounded text-sm ml-4">
                    {video.duration}
                  </span>
                </div>
                
                <p className="text-gray-600 text-sm mb-4">
                  Published: {video.published_date}
                </p>
                
                <div className="bg-blue-50 p-4 rounded-md">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-sm font-medium text-blue-800">
                      {video.has_transcript ? '🤖📜 AI Summary' : '🤖 AI Summary'}
                    </span>
                    {video.has_transcript && (
                      <span className="bg-green-100 text-green-700 text-xs px-2 py-1 rounded-full">
                        Based on transcript
                      </span>
                    )}
                  </div>
                  <div className="text-blue-700 leading-relaxed prose prose-sm max-w-none prose-headings:text-blue-800 prose-strong:text-blue-800 prose-code:text-blue-600 prose-code:bg-blue-100 prose-code:px-1 prose-code:rounded">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {video.summary}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default VideoResults