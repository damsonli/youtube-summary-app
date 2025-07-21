import { useState, useEffect } from 'react'
import axios from 'axios'

const SubscriptionManager = () => {
  const [subscriptions, setSubscriptions] = useState([])
  const [userEmail, setUserEmail] = useState('')
  const [channelUrl, setChannelUrl] = useState('')
  const [channelName, setChannelName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (userEmail) {
      loadUserSubscriptions()
    }
  }, [userEmail])

  const loadUserSubscriptions = async () => {
    try {
      const response = await axios.get(`/api/subscriptions/email/${encodeURIComponent(userEmail)}`)
      setSubscriptions(response.data)
    } catch (err) {
      console.error('Failed to load subscriptions:', err)
    }
  }

  const handleSubscribe = async (e) => {
    e.preventDefault()
    
    if (!userEmail.trim() || !channelUrl.trim() || !channelName.trim()) {
      setError('Please fill in all fields')
      return
    }

    setLoading(true)
    setError('')
    setSuccess('')

    try {
      await axios.post('/api/subscriptions', {
        channel_url: channelUrl.trim(),
        channel_name: channelName.trim(),
        user_email: userEmail.trim()
      })
      
      setSuccess('Successfully subscribed to channel!')
      setChannelUrl('')
      setChannelName('')
      loadUserSubscriptions()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create subscription')
    } finally {
      setLoading(false)
    }
  }

  const handleUnsubscribe = async (subscriptionId) => {
    try {
      await axios.delete(`/api/subscriptions/${subscriptionId}`)
      setSuccess('Successfully unsubscribed!')
      loadUserSubscriptions()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to unsubscribe')
    }
  }

  const extractChannelName = (url) => {
    const match = url.match(/@([^/]+)/)
    return match ? match[1] : ''
  }

  const handleChannelUrlChange = (e) => {
    const url = e.target.value
    setChannelUrl(url)
    
    // Auto-extract channel name if possible
    const extractedName = extractChannelName(url)
    if (extractedName && !channelName) {
      setChannelName(extractedName)
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Subscribe Form */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-2xl font-bold text-gray-800 mb-6">Subscribe to Channel</h2>
        
        <form onSubmit={handleSubscribe} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Your Email
            </label>
            <input
              type="email"
              value={userEmail}
              onChange={(e) => setUserEmail(e.target.value)}
              placeholder="your@email.com"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Channel URL
            </label>
            <input
              type="url"
              value={channelUrl}
              onChange={handleChannelUrlChange}
              placeholder="https://youtube.com/@channelname"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Channel Name
            </label>
            <input
              type="text"
              value={channelName}
              onChange={(e) => setChannelName(e.target.value)}
              placeholder="Channel display name"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          {error && (
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}

          {success && (
            <div className="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded">
              {success}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 font-medium disabled:opacity-50"
          >
            {loading ? 'Subscribing...' : 'Subscribe'}
          </button>
        </form>
      </div>

      {/* Subscriptions List */}
      {userEmail && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-2xl font-bold text-gray-800 mb-6">Your Subscriptions</h2>
          
          {subscriptions.length === 0 ? (
            <div className="text-center py-8">
              <div className="text-gray-400 mb-2">
                <svg className="mx-auto h-12 w-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-1">No subscriptions yet</h3>
              <p className="text-gray-500">Subscribe to channels above to get daily updates</p>
            </div>
          ) : (
            <div className="space-y-4">
              {subscriptions.map((subscription) => (
                <div key={subscription.id} className="border border-gray-200 rounded-lg p-4 flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold text-gray-800">{subscription.channel_name}</h3>
                    <p className="text-sm text-gray-600">{subscription.channel_url}</p>
                    <p className="text-xs text-gray-500">
                      Subscribed: {new Date(subscription.created_at).toLocaleDateString()}
                      {subscription.last_checked && (
                        <span className="ml-2">
                          • Last checked: {new Date(subscription.last_checked).toLocaleDateString()}
                        </span>
                      )}
                    </p>
                  </div>
                  <button
                    onClick={() => handleUnsubscribe(subscription.id)}
                    className="bg-red-600 text-white px-4 py-2 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 text-sm"
                  >
                    Unsubscribe
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default SubscriptionManager