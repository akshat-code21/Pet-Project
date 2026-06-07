'use client'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { LogOut, Moon, Sun, Monitor, User, Shield, Bell, Lock, Mail, Cpu, Play, RefreshCw, Database } from 'lucide-react'
import { useTheme } from 'next-themes'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { supabase } from '@/lib/supabase'
import { useToast } from '@/hooks/use-toast'
import { adminApi } from '@/lib/api'


const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export default function SettingsPage() {
  const { theme, setTheme } = useTheme()
  const router = useRouter()
  const { toast } = useToast()

  // Notification preferences (stored locally until backend supports user metadata)
  const [emailCritical, setEmailCritical] = useState(true)
  const [emailDigest, setEmailDigest] = useState(true)

  // Password change
  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)

  // Scheduler status & triggers
  const [statusData, setStatusData] = useState<{
    scheduler_running: boolean
    jobs: any[]
    pending_content_items: number
  } | null>(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [runningJobs, setRunningJobs] = useState<Record<string, boolean>>({})

  const fetchStatus = async () => {
    try {
      const res = await adminApi.getStatus()
      setStatusData(res.data.data)
    } catch (err: any) {
      console.error('Failed to fetch scheduler status', err)
    } finally {
      setLoadingStatus(false)
    }
  }

  useEffect(() => {
    fetchStatus()
  }, [])

  const handleTriggerJob = async (jobName: string) => {
    setRunningJobs((prev) => ({ ...prev, [jobName]: true }))
    toast({
      title: 'Starting job',
      description: `Triggered job: ${jobName.replace('_', ' ')}. Running in backend...`,
    })
    try {
      const res = await adminApi.triggerJob(jobName)
      if (res.data.error) {
        toast({
          title: 'Job execution failed',
          description: res.data.error,
          variant: 'destructive',
        })
      } else {
        toast({
          title: 'Job completed successfully',
          description: res.data.message || `Job ${jobName.replace('_', ' ')} finished.`,
        })
        fetchStatus()
      }
    } catch (err: any) {
      toast({
        title: 'Network error',
        description: err.response?.data?.error || err.message || 'Failed to trigger job',
        variant: 'destructive',
      })
    } finally {
      setRunningJobs((prev) => ({ ...prev, [jobName]: false }))
    }
  }


  const handleSignOut = async () => {
    await supabase.auth.signOut()
    toast({ title: 'Signed out' })
    router.push('/login')
  }

  const handlePasswordChange = async () => {
    if (newPassword.length < 6) {
      toast({ title: 'Password too short', description: 'Must be at least 6 characters', variant: 'destructive' })
      return
    }
    setChangingPassword(true)
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword })
      if (error) throw error
      toast({ title: 'Password updated successfully' })
      setNewPassword('')
      setShowPasswordForm(false)
    } catch (err: any) {
      toast({ title: 'Error', description: err.message || 'Failed to update password', variant: 'destructive' })
    } finally {
      setChangingPassword(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-8">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="font-display font-bold text-3xl text-foreground">Settings</h1>
        <p className="text-muted-foreground mt-1">Manage your account and preferences</p>
      </motion.div>

      {/* Appearance */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Monitor className="w-4 h-4 text-muted-foreground" />
              <CardTitle className="text-base">Appearance</CardTitle>
            </div>
            <CardDescription>Choose your preferred theme</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
              {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  onClick={() => setTheme(value)}
                  className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all ${
                    theme === value
                      ? 'border-primary bg-primary/5'
                      : 'border-border/50 hover:border-border hover:bg-accent/50'
                  }`}
                >
                  <Icon className={`w-5 h-5 ${theme === value ? 'text-primary' : 'text-muted-foreground'}`} />
                  <span className={`text-sm font-medium ${theme === value ? 'text-primary' : 'text-muted-foreground'}`}>{label}</span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Notifications */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Bell className="w-4 h-4 text-muted-foreground" />
              <CardTitle className="text-base">Notifications</CardTitle>
            </div>
            <CardDescription>Configure email alert preferences</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="email-critical" className="text-sm font-medium">Critical & high severity emails</Label>
                <p className="text-xs text-muted-foreground">Receive email alerts for critical and high-priority events</p>
              </div>
              <Switch
                id="email-critical"
                checked={emailCritical}
                onCheckedChange={(v) => { setEmailCritical(v); toast({ title: `Critical emails ${v ? 'enabled' : 'disabled'}` }) }}
              />
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="email-digest" className="text-sm font-medium">Daily digest email</Label>
                <p className="text-xs text-muted-foreground">Receive a daily summary of all investor activity at 7:00 AM UTC</p>
              </div>
              <Switch
                id="email-digest"
                checked={emailDigest}
                onCheckedChange={(v) => { setEmailDigest(v); toast({ title: `Daily digest ${v ? 'enabled' : 'disabled'}` }) }}
              />
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Account */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-muted-foreground" />
              <CardTitle className="text-base">Account</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between py-2">
              <div>
                <p className="text-sm font-medium text-foreground">Session</p>
                <p className="text-xs text-muted-foreground">Signed in via Supabase Auth</p>
              </div>
              <Badge variant="secondary">Active</Badge>
            </div>
            <Separator />

            {/* Password */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">Password</p>
                  <p className="text-xs text-muted-foreground">Update your account password</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowPasswordForm(!showPasswordForm)}
                >
                  <Lock className="w-3.5 h-3.5" />
                  {showPasswordForm ? 'Cancel' : 'Change'}
                </Button>
              </div>
              {showPasswordForm && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex items-end gap-3"
                >
                  <div className="flex-1 space-y-1.5">
                    <Label htmlFor="new-password" className="text-xs">New password</Label>
                    <Input
                      id="new-password"
                      type="password"
                      placeholder="Min 6 characters"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                    />
                  </div>
                  <Button
                    size="sm"
                    disabled={changingPassword || newPassword.length < 6}
                    onClick={handlePasswordChange}
                  >
                    {changingPassword ? 'Updating...' : 'Update'}
                  </Button>
                </motion.div>
              )}
            </div>

            <Separator />
            <Button variant="destructive" size="sm" onClick={handleSignOut} className="w-full sm:w-auto">
              <LogOut className="w-4 h-4" /> Sign out
            </Button>
          </CardContent>
        </Card>
      </motion.div>

      {/* Scheduler Controls */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-muted-foreground" />
                <CardTitle className="text-base">Scheduler & Ingestion Controls</CardTitle>
              </div>
              <CardDescription>Manually trigger scheduled data ingestion and pipeline jobs</CardDescription>
            </div>
            <Button
              variant="outline"
              size="icon"
              onClick={fetchStatus}
              disabled={loadingStatus}
              className="h-8 w-8"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingStatus ? 'animate-spin' : ''}`} />
            </Button>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Status Summary */}
            <div className="grid grid-cols-2 gap-4">
              <div className="flex items-center gap-2.5 p-3.5 rounded-xl border border-border/50 bg-muted/20">
                <div className={`w-2 h-2 rounded-full ${statusData?.scheduler_running ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
                <div>
                  <p className="text-xs text-muted-foreground font-medium">Scheduler Status</p>
                  <p className="text-sm font-semibold mt-0.5">
                    {loadingStatus ? 'Loading...' : statusData?.scheduler_running ? 'Active & Running' : 'Stopped/Disabled'}
                  </p>
                </div>
              </div>
              
              <div className="flex items-center gap-2.5 p-3.5 rounded-xl border border-border/50 bg-muted/20">
                <Database className="w-4 h-4 text-primary" />
                <div>
                  <p className="text-xs text-muted-foreground font-medium">Pending Items</p>
                  <p className="text-sm font-semibold mt-0.5">
                    {loadingStatus ? 'Loading...' : statusData?.pending_content_items ?? 0} items
                  </p>
                </div>
              </div>
            </div>

            {/* List of Jobs */}
            <div className="space-y-3">
              {[
                { id: 'process_pending', label: 'Process Pending Content', desc: 'Vectorize pending articles, extract entities, theses, and files.' },
                { id: 'ingest_sec_13f', label: 'SEC 13F Ingestion', desc: 'Scrape latest SEC 13F filing updates for tracked funds.' },
                { id: 'ingest_rss', label: 'RSS News Ingestion', desc: 'Fetch updates from tracked investor blogs and news feeds.' },
                { id: 'ingest_websites', label: 'Website Ingestion', desc: 'Crawl targeted investor sites and web content.' },
                { id: 'ingest_youtube', label: 'YouTube Ingestion', desc: 'Check for new video releases and fetch transcripts.' },
                { id: 'daily_digest', label: 'Generate Daily Digest', desc: 'Synthesize reports from the last 24h and trigger emails.' },
              ].map((job) => (
                <div key={job.id} className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-xl border border-border/40 hover:border-border/80 transition-colors gap-3 bg-card">
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-foreground">{job.label}</p>
                    <p className="text-xs text-muted-foreground leading-relaxed max-w-md">{job.desc}</p>
                  </div>
                  <Button
                    size="sm"
                    className="self-end sm:self-center min-w-[100px] gap-1.5"
                    disabled={runningJobs[job.id]}
                    onClick={() => handleTriggerJob(job.id)}
                  >
                    <Play className={`w-3.5 h-3.5 ${runningJobs[job.id] ? 'animate-spin' : ''}`} />
                    {runningJobs[job.id] ? 'Running...' : 'Run Now'}
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Platform Info */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-muted-foreground" />
              <CardTitle className="text-base">Platform</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 text-sm">
              {[
                ['Backend', 'FastAPI + LangGraph'],
                ['Database', 'PostgreSQL + pgvector'],
                ['AI Models', 'GPT-4o / GPT-4o-mini'],
                ['Auth', 'Supabase Auth'],
                ['Embeddings', 'text-embedding-3-small'],
                ['Scheduler', 'APScheduler'],
              ].map(([label, value]) => (
                <div key={label} className="p-3 rounded-lg bg-muted/50">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="font-mono text-xs text-foreground mt-0.5">{value}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  )
}
