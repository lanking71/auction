def setupbrowser(self):

    options = uc.ChromeOptions()
    
    # 기본 설정
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--window-size=1024,768')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-automation')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-web-security')
    options.add_argument('--allow-running-insecure-content')
    options.add_argument(f'--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
    
    
    try:
        self.browser = uc.Chrome(
            options=options,
            use_subprocess=True
        )

        # CDP 명령어로 자동화 감지 우회
        self.browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            '''
        })

        # 기본 설정
        self.browser.set_window_size(1024, 768)
        time.sleep(1)  # 창 크기 적용 대기

        # 페이지 로드 대기 설정
        self.browser.set_page_load_timeout(30)
        self.browser.implicitly_wait(10)
        
        return self.browser
    
    except Exception as e:
        self.auction_operation_signal.emit(f"브라우저 설정 실패: {str(e)}")
        return False