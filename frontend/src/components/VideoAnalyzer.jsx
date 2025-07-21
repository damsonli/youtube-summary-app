import { useState } from 'react'
import axios from 'axios'

const VideoAnalyzer = ({ onResults, onLoading, onProgress }) => {
  const [url, setUrl] = useState('')
  const [analysisType, setAnalysisType] = useState('video')
  const [channelOptions, setChannelOptions] = useState({
    limit: 5
  })
  const [error, setError] = useState('')
  const [progress, setProgress] = useState({ message: '', step: 0, total: 0, progress: 0 })

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    if (!url.trim()) {
      setError('Please enter a YouTube URL')
      return
    }

    setError('')
    onLoading(true)
    onResults([])
    setProgress({ message: 'Starting analysis...', step: 0, total: 0, progress: 0 })

    try {
      const endpoint = analysisType === 'video' ? '/api/analyze/video/stream' : '/api/analyze/channel/stream'
      const payload = analysisType === 'video' 
        ? { url: url.trim() }
        : { 
            url: url.trim(), 
            limit: channelOptions.limit
          }

      console.log('Making request to:', endpoint, 'with payload:', payload)

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })

      console.log('Response status:', response.status)
      console.log('Response headers:', response.headers)

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        
        // Keep the last incomplete line in buffer
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const jsonStr = line.slice(6).trim()
              console.log('Received data:', jsonStr)
              if (jsonStr) {
                const data = JSON.parse(jsonStr)
                console.log('Parsed data:', data)
                
                if (data.type === 'progress') {
                  const progressData = {
                    message: data.message,
                    step: data.step,
                    total: data.total,
                    progress: data.progress
                  }
                  console.log('Setting progress:', progressData)
                  setProgress(progressData)
                  onProgress(progressData)
                } else if (data.type === 'result') {
                  const results = Array.isArray(data.data) ? data.data : [data.data]
                  console.log('Setting results:', results)
                  onResults(results)
                } else if (data.type === 'error') {
                  console.log('Error received:', data.message)
                  setError(data.message)
                }
              }
            } catch (e) {
              console.error('Error parsing progress data:', e, 'Line:', line)
            }
          }
        }
      }
      
    } catch (err) {
      console.error('Streaming failed, falling back to regular endpoint:', err)
      
      // Fallback to regular endpoints
      try {
        const fallbackEndpoint = analysisType === 'video' ? '/api/analyze/video' : '/api/analyze/channel'
        const fallbackPayload = analysisType === 'video' 
          ? { url: url.trim() }
          : { 
              url: url.trim(), 
              limit: channelOptions.limit
            }

        const response = await axios.post(fallbackEndpoint, fallbackPayload)
        const results = Array.isArray(response.data) ? response.data : [response.data]
        onResults(results)
      } catch (fallbackErr) {
        setError(fallbackErr.response?.data?.detail || fallbackErr.message || 'Failed to analyze video/channel')
      }
    } finally {
      onLoading(false)
      setProgress({ message: '', step: 0, total: 0, progress: 0 })
    }
  }

  const isChannelUrl = (url) => {
    return url.includes('/@') || url.includes('/channel/') || url.includes('/c/')
  }

  const handleUrlChange = (e) => {
    const newUrl = e.target.value
    setUrl(newUrl)
    
    // Auto-detect if it's a channel URL
    if (isChannelUrl(newUrl)) {
      setAnalysisType('channel')
    } else {
      setAnalysisType('video')
    }
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* URL Input */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            YouTube URL
          </label>
          <input
            type="url"
            value={url}
            onChange={handleUrlChange}
            placeholder="https://youtube.com/watch?v=... or https://youtube.com/@channel"
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* Analysis Type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Analysis Type
          </label>
          <div className="flex space-x-4">
            <label className="flex items-center">
              <input
                type="radio"
                value="video"
                checked={analysisType === 'video'}
                onChange={(e) => setAnalysisType(e.target.value)}
                className="mr-2"
              />
              Single Video
            </label>
            <label className="flex items-center">
              <input
                type="radio"
                value="channel"
                checked={analysisType === 'channel'}
                onChange={(e) => setAnalysisType(e.target.value)}
                className="mr-2"
              />
              Channel Videos
            </label>
          </div>
        </div>

        {/* Channel Options */}
        {analysisType === 'channel' && (
          <div className="bg-gray-50 p-4 rounded-md space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Number of Videos
              </label>
              <select
                value={channelOptions.limit}
                onChange={(e) => setChannelOptions({...channelOptions, limit: parseInt(e.target.value)})}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={3}>3 videos</option>
                <option value={5}>5 videos</option>
                <option value={10}>10 videos</option>
                <option value={15}>15 videos</option>
              </select>
            </div>

          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          className="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 font-medium"
        >
          {analysisType === 'video' ? 'Analyze Video' : 'Analyze Channel'}
        </button>
      </form>
    </div>
  )
}

export default VideoAnalyzer