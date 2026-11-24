/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Which windows the screen capturer may be asked about
// (third_party/libwebrtc/modules/desktop_capture/win/
// StealthWindowInputDesktop.h): a window of this process created on another
// Win32 desktop object is off the input desktop, every other window is on it.

#include <windows.h>

#include <future>
#include <memory>
#include <thread>

#include "gtest/gtest.h"
#include "modules/desktop_capture/win/StealthWindowInputDesktop.h"
#include "modules/desktop_capture/win/desktop.h"

namespace {

// A window of this process, on the desktop its own thread runs on: the
// default one, or a desktop object created for the test (aDesktopName). The
// thread keeps the window alive until the object is destroyed.
class WindowOnItsOwnThread {
 public:
  explicit WindowOnItsOwnThread(const wchar_t* aDesktopName) {
    std::promise<HWND> created;
    std::future<HWND> hwnd = created.get_future();
    std::future<void> release = mRelease.get_future();
    mThread = std::thread([aDesktopName, created = std::move(created),
                           release = std::move(release)]() mutable {
      HDESK desktop = nullptr;
      if (aDesktopName) {
        desktop = ::CreateDesktopW(aDesktopName, nullptr, nullptr, 0,
                                   GENERIC_ALL, nullptr);
        if (!desktop || !::SetThreadDesktop(desktop)) {
          created.set_value(nullptr);
          if (desktop) {
            ::CloseDesktop(desktop);
          }
          return;
        }
      }
      HWND window = ::CreateWindowExW(0, L"STATIC", L"stealth-test", WS_POPUP,
                                      0, 0, 10, 10, nullptr, nullptr,
                                      ::GetModuleHandleW(nullptr), nullptr);
      created.set_value(window);
      release.wait();
      if (window) {
        ::DestroyWindow(window);
      }
      if (desktop) {
        ::CloseDesktop(desktop);
      }
    });
    mWindow = hwnd.get();
  }

  ~WindowOnItsOwnThread() {
    mRelease.set_value();
    mThread.join();
  }

  HWND Window() const { return mWindow; }

 private:
  std::promise<void> mRelease;
  std::thread mThread;
  HWND mWindow = nullptr;
};

}  // namespace

TEST(StealthWindowInputDesktop, OnlyAWindowOfThisProcessOnAnotherDesktopIsOff)
{
  // The input desktop must be readable, or every answer is "on" by design.
  std::unique_ptr<webrtc::Desktop> input(webrtc::Desktop::GetInputDesktop());
  ASSERT_TRUE(input);

  // The control: a window on the desktop its thread started on, the input one.
  {
    WindowOnItsOwnThread onInput(nullptr);
    ASSERT_TRUE(onInput.Window());
    EXPECT_TRUE(mozilla::StealthIsWindowOnInputDesktop(onInput.Window()));
    EXPECT_FALSE(mozilla::StealthIsOffInputDesktop(onInput.Window()));
  }

  // A window created on a second desktop object.
  {
    WindowOnItsOwnThread hidden(L"StealthHiddenDesktopTest");
    ASSERT_TRUE(hidden.Window());
    EXPECT_FALSE(mozilla::StealthIsWindowOnInputDesktop(hidden.Window()));
    EXPECT_TRUE(mozilla::StealthIsOffInputDesktop(hidden.Window()));
  }

  // A window of another process cannot be asked: reported as on.
  HWND other = ::GetDesktopWindow();
  ASSERT_TRUE(other);
  EXPECT_TRUE(mozilla::StealthIsWindowOnInputDesktop(other));

  // No window, so no thread: reported as on.
  EXPECT_TRUE(mozilla::StealthIsWindowOnInputDesktop(nullptr));
  EXPECT_FALSE(mozilla::StealthIsOffInputDesktop(nullptr));
}
