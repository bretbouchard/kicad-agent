source "https://rubygems.org"

gem "fastlane", "~> 2.225"
gem "cocoapods", "~> 1.16"  # Required by some fastlane actions

plugins_path = File.join(File.dirname(__FILE__), "fastlane", "Pluginfile")
eval_gemfile(plugins_path) if File.exist?(plugins_path)
