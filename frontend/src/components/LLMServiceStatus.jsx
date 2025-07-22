import { useState, useEffect } from 'react'

const LLMServiceStatus = () => {
  const [serviceInfo, setServiceInfo] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchServiceInfo()
  }, [])

  const fetchServiceInfo = async () => {
    try {
      const response = await fetch('http://localhost:8000/llm-service')
      const data = await response.json()
      setServiceInfo(data)
    } catch (error) {
      console.error('Failed to fetch LLM service info:', error)
      setServiceInfo({ error: 'Failed to connect to API' })
    } finally {
      setLoading(false)
    }
  }

  const getServiceIcon = (service) => {
    switch (service) {
      case 'ollama':
        return '🏠'
      case 'openai':
        return '☁️'
      default:
        return '🤖'
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'connected':
        return '🟢'
      case 'disconnected':
        return '🔴'
      case 'error':
        return '❌'
      default:
        return '🟡'
    }
  }

  const getStatusText = (status) => {
    switch (status) {
      case 'connected':
        return 'Connected'
      case 'disconnected':
        return 'Disconnected'
      case 'error':
        return 'Error'
      default:
        return 'Unknown'
    }
  }

  if (loading) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-4">
        <div className="flex items-center text-sm text-gray-600">
          <div className="animate-pulse">Loading LLM service info...</div>
        </div>
      </div>
    )
  }

  if (serviceInfo?.error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
        <div className="flex items-center text-sm text-red-700">
          <span className="mr-2">❌</span>
          <span>LLM Service: {serviceInfo.error}</span>
        </div>
      </div>
    )
  }

  const { service, status, model, host, has_api_key } = serviceInfo

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center">
          <span className="mr-2 text-lg">{getServiceIcon(service)}</span>
          <span className="font-medium text-blue-900">
            {service === 'ollama' ? 'Ollama (Self-hosted)' : 'OpenAI (Cloud)'}
          </span>
          <span className="mx-2 text-blue-600">•</span>
          <span className="text-blue-700">{model}</span>
        </div>
        
        <div className="flex items-center">
          <span className="mr-1">{getStatusIcon(status)}</span>
          <span className={`text-sm font-medium ${
            status === 'connected' ? 'text-green-700' : 
            status === 'disconnected' ? 'text-red-700' : 
            'text-yellow-700'
          }`}>
            {getStatusText(status)}
          </span>
        </div>
      </div>
      
      {service === 'ollama' && host && (
        <div className="mt-1 text-xs text-blue-600">
          Host: {host}
        </div>
      )}
      
      {service === 'openai' && (
        <div className="mt-1 text-xs text-blue-600">
          API Key: {has_api_key ? 'Configured' : 'Not configured'}
        </div>
      )}
      
      {serviceInfo.error && (
        <div className="mt-1 text-xs text-red-600">
          Error: {serviceInfo.error}
        </div>
      )}
    </div>
  )
}

export default LLMServiceStatus